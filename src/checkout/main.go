// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0
package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/log/global"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.opentelemetry.io/otel/trace"

	"github.com/IBM/sarama"
	"github.com/google/uuid"
	otelhooks "github.com/open-feature/go-sdk-contrib/hooks/open-telemetry/pkg"
	flagd "github.com/open-feature/go-sdk-contrib/providers/flagd/pkg"
	"github.com/open-feature/go-sdk/openfeature"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	otelcodes "go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploggrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"

	sdklog "go.opentelemetry.io/otel/sdk/log"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	sdkresource "go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"

	pb "github.com/open-telemetry/techx-corp/src/checkout/genproto/oteldemo"
	"github.com/open-telemetry/techx-corp/src/checkout/kafka"
	"github.com/open-telemetry/techx-corp/src/checkout/money"
	"github.com/open-telemetry/techx-corp/src/checkout/outbox"
)

//go:generate go install google.golang.org/protobuf/cmd/protoc-gen-go
//go:generate go install google.golang.org/grpc/cmd/protoc-gen-go-grpc
//go:generate protoc --go_out=./ --go-grpc_out=./ --proto_path=../../pb ../../pb/demo.proto

var logger *slog.Logger
var tracer trace.Tracer
var resource *sdkresource.Resource
var initResourcesOnce sync.Once

func initResource() *sdkresource.Resource {
	initResourcesOnce.Do(func() {
		extraResources, _ := sdkresource.New(
			context.Background(),
			sdkresource.WithOS(),
			sdkresource.WithProcess(),
			sdkresource.WithContainer(),
			sdkresource.WithHost(),
		)
		resource, _ = sdkresource.Merge(
			sdkresource.Default(),
			extraResources,
		)
	})
	return resource
}

func initTracerProvider() *sdktrace.TracerProvider {
	ctx := context.Background()

	exporter, err := otlptracegrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("new otlp trace grpc exporter failed: %v", err))
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(initResource()),
	)
	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	return tp
}

func initMeterProvider() *sdkmetric.MeterProvider {
	ctx := context.Background()

	exporter, err := otlpmetricgrpc.New(ctx)
	if err != nil {
		logger.Error(fmt.Sprintf("new otlp metric grpc exporter failed: %v", err))
	}

	mp := sdkmetric.NewMeterProvider(
		sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter)),
		sdkmetric.WithResource(initResource()),
	)
	otel.SetMeterProvider(mp)
	return mp
}

func initLoggerProvider() *sdklog.LoggerProvider {
	ctx := context.Background()

	logExporter, err := otlploggrpc.New(ctx)
	if err != nil {
		return nil
	}

	loggerProvider := sdklog.NewLoggerProvider(
		sdklog.WithProcessor(sdklog.NewBatchProcessor(logExporter)),
	)
	global.SetLoggerProvider(loggerProvider)

	return loggerProvider
}

type checkout struct {
	productCatalogSvcAddr string
	cartSvcAddr           string
	currencySvcAddr       string
	shippingSvcAddr       string
	emailSvcAddr          string
	paymentSvcAddr        string
	kafkaBrokerSvcAddr    string
	kafkaProducerMu       sync.Mutex
	pb.UnimplementedCheckoutServiceServer
	KafkaProducerClient     sarama.AsyncProducer
	Outbox                  *outbox.Store
	shippingSvcClient       pb.ShippingServiceClient
	productCatalogSvcClient pb.ProductCatalogServiceClient
	cartSvcClient           pb.CartServiceClient
	currencySvcClient       pb.CurrencyServiceClient
	emailSvcClient          pb.EmailServiceClient
	paymentSvcClient        pb.PaymentServiceClient
}

func main() {
	var port string
	mustMapEnv(&port, "CHECKOUT_PORT")

	tp := initTracerProvider()
	defer func() {
		if err := tp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down tracer provider: %v", err))
		}
	}()

	mp := initMeterProvider()
	defer func() {
		if err := mp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down meter provider: %v", err))
		}
	}()

	lp := initLoggerProvider()
	defer func() {
		if err := lp.Shutdown(context.Background()); err != nil {
			logger.Error(fmt.Sprintf("Error shutting down logger provider: %v", err))
		}
	}()

	// this *must* be called after the logger provider is initialized
	// otherwise the Sarama producer in kafka/producer.go will not be
	// able to log properly
	logger = slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	err := runtime.Start(runtime.WithMinimumReadMemStatsInterval(time.Second))
	if err != nil {
		logger.Error((err.Error()))
	}

	provider, err := flagd.NewProvider()
	if err != nil {
		logger.Error(fmt.Sprintf("Error creating flagd provider: %v", err))
	}

	openfeature.SetProvider(provider)
	openfeature.AddHooks(otelhooks.NewTracesHook())

	tracer = tp.Tracer("checkout")

	svc := new(checkout)

	mustMapEnv(&svc.shippingSvcAddr, "SHIPPING_ADDR")
	c := mustCreateClient(svc.shippingSvcAddr)
	svc.shippingSvcClient = pb.NewShippingServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.productCatalogSvcAddr, "PRODUCT_CATALOG_ADDR")
	c = mustCreateClient(svc.productCatalogSvcAddr)
	svc.productCatalogSvcClient = pb.NewProductCatalogServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.cartSvcAddr, "CART_ADDR")
	c = mustCreateClient(svc.cartSvcAddr)
	svc.cartSvcClient = pb.NewCartServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.currencySvcAddr, "CURRENCY_ADDR")
	c = mustCreateClient(svc.currencySvcAddr)
	svc.currencySvcClient = pb.NewCurrencyServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.emailSvcAddr, "EMAIL_ADDR")
	c = mustCreateClient(svc.emailSvcAddr)
	svc.emailSvcClient = pb.NewEmailServiceClient(c)
	defer c.Close()

	mustMapEnv(&svc.paymentSvcAddr, "PAYMENT_ADDR")
	c = mustCreateClient(svc.paymentSvcAddr)
	svc.paymentSvcClient = pb.NewPaymentServiceClient(c)
	defer c.Close()

	svc.kafkaBrokerSvcAddr = os.Getenv("KAFKA_ADDR")
	outboxTable := os.Getenv("CHECKOUT_OUTBOX_TABLE")

	if svc.kafkaBrokerSvcAddr != "" {
		// With a durable outbox, producer creation belongs to the background
		// worker. A dead broker must not delay checkout startup/readiness.
		if outboxTable == "" {
			svc.KafkaProducerClient, err = kafka.CreateKafkaProducer([]string{svc.kafkaBrokerSvcAddr}, logger)
			if err != nil {
				logger.Error(fmt.Sprintf("failed to create Kafka producer (order post-processing disabled): %v", err))
				svc.KafkaProducerClient = nil
			}
		}

		// Start background Kafka consumer group (independent of producer success).
		go func() {
			config := sarama.NewConfig()
			config.Consumer.Offsets.Initial = sarama.OffsetOldest
			config.Version = kafka.ProtocolVersion
			if os.Getenv("KAFKA_TLS") == "true" {
				config.Net.TLS.Enable = true
				config.Net.TLS.Config = &tls.Config{
					InsecureSkipVerify: true,
				}
			}

			brokers := strings.Split(svc.kafkaBrokerSvcAddr, ",")
			consumerGroup, err := sarama.NewConsumerGroup(brokers, "checkout-group", config)
			if err != nil {
				logger.Error(fmt.Sprintf("Failed to create consumer group: %+v", err))
				return
			}
			defer consumerGroup.Close()

			handler := &ApprovedOrderConsumer{checkoutSvc: svc}
			topics := []string{"orders-approved", "orders-cancelled"}
			logger.Info(fmt.Sprintf("Starting consumer group for topics: %v", topics))

			ctx := context.Background()
			for {
				err := consumerGroup.Consume(ctx, topics, handler)
				if err != nil {
					logger.Error(fmt.Sprintf("Error in consumer group Consume: %+v", err))
				}
				if ctx.Err() != nil {
					return
				}
			}
		}()
	}

	workerCtx, stopWorkers := context.WithCancel(context.Background())
	defer stopWorkers()
	if outboxTable != "" {
		svc.Outbox, err = outbox.New(workerCtx, outboxTable, logger)
		if err != nil {
			logger.Error(fmt.Sprintf("failed to initialize durable checkout outbox: %v", err))
		} else {
			go svc.Outbox.Run(workerCtx, func(ctx context.Context, event outbox.Event) error {
				result := new(pb.OrderResult)
				if err := proto.Unmarshal(event.Payload, result); err != nil {
					return fmt.Errorf("decode outbox event %s: %w", event.ID, err)
				}
				if err := svc.ensureKafkaProducer(); err != nil {
					return err
				}
				return svc.sendToPostProcessor(ctx, result)
			})
			logger.Info("durable checkout outbox worker started", "table", outboxTable)
		}
	}

	logger.Info(fmt.Sprintf("service config: %+v", svc))

	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		logger.Error(err.Error())
	}

	var srv = grpc.NewServer(
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	)
	pb.RegisterCheckoutServiceServer(srv, svc)

	healthcheck := health.NewServer()
	healthpb.RegisterHealthServer(srv, healthcheck)
	logger.Info(fmt.Sprintf("starting to listen on tcp: %q", lis.Addr().String()))
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM, syscall.SIGKILL)
	defer cancel()

	go func() {
		if err := srv.Serve(lis); err != nil {
			logger.Error(err.Error())
		}
	}()

	<-ctx.Done()

	stopWorkers()
	srv.GracefulStop()
	logger.Info("Checkout gRPC server stopped")
}

func mustMapEnv(target *string, envKey string) {
	v := os.Getenv(envKey)
	if v == "" {
		panic(fmt.Sprintf("environment variable %q not set", envKey))
	}
	*target = v
}

func (cs *checkout) Check(ctx context.Context, req *healthpb.HealthCheckRequest) (*healthpb.HealthCheckResponse, error) {
	return &healthpb.HealthCheckResponse{Status: healthpb.HealthCheckResponse_SERVING}, nil
}

func (cs *checkout) Watch(req *healthpb.HealthCheckRequest, ws healthpb.Health_WatchServer) error {
	return status.Errorf(codes.Unimplemented, "health check via Watch not implemented")
}

func (cs *checkout) PlaceOrder(ctx context.Context, req *pb.PlaceOrderRequest) (*pb.PlaceOrderResponse, error) {
	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		attribute.String("app.user.id", req.UserId),
		attribute.String("app.user.currency", req.UserCurrency),
	)
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "[PlaceOrder]",
		slog.String("user_id", req.UserId),
		slog.String("user_currency", req.UserCurrency),
	)

	var err error
	defer func() {
		if err != nil {
			span.AddEvent("error", trace.WithAttributes(semconv.ExceptionMessageKey.String(err.Error())))
		}
	}()

	orderID, err := uuid.NewUUID()
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to generate order uuid")
	}

	prep, err := cs.prepareOrderItemsAndShippingQuoteFromCart(ctx, req.UserId, req.UserCurrency, req.Address)
	if err != nil {
		return nil, status.Error(codes.Internal, err.Error())
	}
	span.AddEvent("prepared")

	total := &pb.Money{CurrencyCode: req.UserCurrency,
		Units: 0,
		Nanos: 0}
	total = money.Must(money.Sum(total, prep.shippingCostLocalized))
	for _, it := range prep.orderItems {
		multPrice := money.MultiplySlow(it.Cost, uint32(it.GetItem().GetQuantity()))
		total = money.Must(money.Sum(total, multPrice))
	}

	txID, err := cs.chargeCard(ctx, total, req.CreditCard)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to charge card: %+v", err)
	}

	span.AddEvent("charged",
		trace.WithAttributes(attribute.String("app.payment.transaction.id", txID)))
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "payment went through",
		slog.String("transaction_id", txID),
	)

	// In pre-auth/hold, shipping is deferred until after fraud check.
	shippingTrackingID := "PENDING_SHIPPING"
	shippingTrackingAttribute := attribute.String("app.shipping.tracking.id", shippingTrackingID)
	span.AddEvent("hold", trace.WithAttributes(shippingTrackingAttribute))

	_ = cs.emptyUserCart(ctx, req.UserId)

	orderResult := &pb.OrderResult{
		OrderId:            orderID.String(),
		ShippingTrackingId: shippingTrackingID,
		ShippingCost:       prep.shippingCostLocalized,
		ShippingAddress:    req.Address,
		Items:              prep.orderItems,
	}

	shippingCostFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", prep.shippingCostLocalized.GetUnits(), prep.shippingCostLocalized.GetNanos()/1000000000), 64)
	totalPriceFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", total.GetUnits(), total.GetNanos()/1000000000), 64)

	span.SetAttributes(
		attribute.String("app.order.id", orderID.String()),
		attribute.Float64("app.shipping.amount", shippingCostFloat),
		attribute.Float64("app.order.amount", totalPriceFloat),
		attribute.Int("app.order.items.count", len(prep.orderItems)),
		shippingTrackingAttribute,
	)
	logger.LogAttrs(
		ctx,
		slog.LevelInfo, "order placed",
		slog.String("app.order.id", orderID.String()),
		slog.Float64("app.shipping.amount", shippingCostFloat),
		slog.Float64("app.order.amount", totalPriceFloat),
		slog.Int("app.order.items.count", len(prep.orderItems)),
		slog.String("app.shipping.tracking.id", shippingTrackingID),
	)

	if err := cs.sendOrderConfirmation(ctx, req.Email, orderResult); err != nil {
		logger.Warn(fmt.Sprintf("failed to send order confirmation for order %s: %+v", orderID.String(), err))
	} else {
		logger.Info(fmt.Sprintf("order confirmation email sent for order %s", orderID.String()))
	}

	// Production persists the event before returning and publishes it from a
	// background worker. Kafka availability therefore cannot delay checkout.
	if cs.Outbox != nil {
		message, marshalErr := proto.Marshal(orderResult)
		if marshalErr != nil {
			logger.Error("failed to encode checkout outbox event", "order_id", orderID.String(), "error", marshalErr)
		} else {
			outboxCtx, cancel := context.WithTimeout(context.Background(), 750*time.Millisecond)
			enqueueErr := cs.Outbox.Enqueue(outboxCtx, outbox.Event{ID: orderID.String(), Payload: message})
			cancel()
			if enqueueErr != nil {
				// Payment has already succeeded, so returning an error would invite a
				// duplicate charge. DynamoDB is Multi-AZ; surface the exceptional write
				// failure through telemetry and the outbox alert instead.
				logger.Error("failed to persist checkout outbox event", "order_id", orderID.String(), "error", enqueueErr)
			}
		}
	} else if cs.kafkaBrokerSvcAddr != "" && cs.KafkaProducerClient != nil {
		// Development compatibility path when no durable outbox is configured.
		logger.Info("sending to postProcessor")
		_ = cs.sendToPostProcessor(ctx, orderResult)
	} else if cs.kafkaBrokerSvcAddr != "" {
		logger.Warn("skipping order post-processing: Kafka producer is not available")
	}

	resp := &pb.PlaceOrderResponse{Order: orderResult}
	return resp, nil
}

type orderPrep struct {
	orderItems            []*pb.OrderItem
	cartItems             []*pb.CartItem
	shippingCostLocalized *pb.Money
}

func (cs *checkout) prepareOrderItemsAndShippingQuoteFromCart(ctx context.Context, userID, userCurrency string, address *pb.Address) (orderPrep, error) {

	ctx, span := tracer.Start(ctx, "prepareOrderItemsAndShippingQuoteFromCart")
	defer span.End()

	var out orderPrep
	cartItems, err := cs.getUserCart(ctx, userID)
	if err != nil {
		return out, fmt.Errorf("cart failure: %+v", err)
	}
	if len(cartItems) == 0 {
		return out, fmt.Errorf("cart is empty")
	}
	orderItems, err := cs.prepOrderItems(ctx, cartItems, userCurrency)
	if err != nil {
		return out, fmt.Errorf("failed to prepare order: %+v", err)
	}
	shippingUSD, err := cs.quoteShipping(ctx, address, cartItems)
	if err != nil {
		return out, fmt.Errorf("shipping quote failure: %+v", err)
	}
	shippingPrice, err := cs.convertCurrency(ctx, shippingUSD, userCurrency)
	if err != nil {
		return out, fmt.Errorf("failed to convert shipping cost to currency: %+v", err)
	}

	out.shippingCostLocalized = shippingPrice
	out.cartItems = cartItems
	out.orderItems = orderItems

	var totalCart int32
	for _, ci := range cartItems {
		totalCart += ci.Quantity
	}
	shippingCostFloat, _ := strconv.ParseFloat(fmt.Sprintf("%d.%02d", shippingPrice.GetUnits(), shippingPrice.GetNanos()/1000000000), 64)

	span.SetAttributes(
		attribute.Float64("app.shipping.amount", shippingCostFloat),
		attribute.Int("app.cart.items.count", int(totalCart)),
		attribute.Int("app.order.items.count", len(orderItems)),
	)
	return out, nil
}

func mustCreateClient(svcAddr string) *grpc.ClientConn {
	c, err := grpc.NewClient(svcAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler()),
	)
	if err != nil {
		logger.Error(fmt.Sprintf("could not connect to %s service, err: %+v", svcAddr, err))
	}

	return c
}

// shipping HTTP DTOs match src/shipping GetQuoteRequest / ShipOrderRequest.
// Do not marshal protobuf messages with encoding/json: nil slices become null and
// omitempty drops empty address fields, both of which cause shipping HTTP 400.
type shippingCartItem struct {
	ProductID string `json:"product_id"`
	Quantity  uint32 `json:"quantity"`
}

type shippingAddress struct {
	StreetAddress string `json:"street_address"`
	City          string `json:"city"`
	State         string `json:"state"`
	Country       string `json:"country"`
	ZipCode       string `json:"zip_code"`
}

type shippingRequest struct {
	Address *shippingAddress   `json:"address"`
	Items   []shippingCartItem `json:"items"`
}

func buildShippingRequestPayload(address *pb.Address, items []*pb.CartItem) ([]byte, error) {
	req := shippingRequest{
		// Always a JSON array ([]), never null — shipping requires Vec<CartItem>.
		Items: make([]shippingCartItem, 0, len(items)),
	}
	if address != nil {
		req.Address = &shippingAddress{
			StreetAddress: address.GetStreetAddress(),
			City:          address.GetCity(),
			State:         address.GetState(),
			Country:       address.GetCountry(),
			ZipCode:       address.GetZipCode(),
		}
	}
	for _, item := range items {
		if item == nil {
			continue
		}
		qty := item.GetQuantity()
		if qty < 0 {
			return nil, fmt.Errorf("invalid cart item quantity: %d", qty)
		}
		req.Items = append(req.Items, shippingCartItem{
			ProductID: item.GetProductId(),
			Quantity:  uint32(qty),
		})
	}
	return json.Marshal(req)
}

func (cs *checkout) quoteShipping(ctx context.Context, address *pb.Address, items []*pb.CartItem) (*pb.Money, error) {
	quotePayload, err := buildShippingRequestPayload(address, items)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal ship order request: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.shippingSvcAddr+"/get-quote", "application/json", bytes.NewBuffer(quotePayload))
	if err != nil {
		return nil, fmt.Errorf("failed POST to shipping service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("failed POST to shipping service: expected 200, got %d", resp.StatusCode)
	}

	shippingQuoteBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read shipping quote response: %+v", err)
	}

	var quoteResp struct {
		CostUsd *pb.Money `json:"cost_usd"`
	}
	if err := json.Unmarshal(shippingQuoteBytes, &quoteResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal shipping quote: %+v", err)
	}
	if quoteResp.CostUsd == nil {
		return nil, fmt.Errorf("shipping quote missing cost_usd field")
	}

	return quoteResp.CostUsd, nil
}

func (cs *checkout) getUserCart(ctx context.Context, userID string) ([]*pb.CartItem, error) {
	cart, err := cs.cartSvcClient.GetCart(ctx, &pb.GetCartRequest{UserId: userID})
	if err != nil {
		return nil, fmt.Errorf("failed to get user cart during checkout: %+v", err)
	}
	items := cart.GetItems()
	if items == nil {
		return []*pb.CartItem{}, nil
	}
	return items, nil
}

func (cs *checkout) emptyUserCart(ctx context.Context, userID string) error {
	var lastErr error
	for attempt := 1; attempt <= emptyCartMaxAttempts; attempt++ {
		if err := ctx.Err(); err != nil {
			return fmt.Errorf("failed to empty user cart during checkout: %+v", err)
		}

		if _, err := cs.cartSvcClient.EmptyCart(ctx, &pb.EmptyCartRequest{UserId: userID}); err == nil {
			recordCartCleanupSucceeded(ctx, userID, attempt)
			return nil
		} else {
			lastErr = err
			if attempt == emptyCartMaxAttempts {
				break
			}

			backoff := emptyCartBaseBackoff * time.Duration(1<<(attempt-1))
			logger.LogAttrs(ctx, slog.LevelWarn, "cart cleanup failed; retrying",
				slog.String("user_id", userID),
				slog.Int("attempt", attempt),
				slog.Int("max_attempts", emptyCartMaxAttempts),
				slog.String("backoff", backoff.String()),
				slog.String("error", err.Error()),
			)
			timer := time.NewTimer(backoff)
			select {
			case <-ctx.Done():
				timer.Stop()
				return fmt.Errorf("failed to empty user cart during checkout: %+v", ctx.Err())
			case <-timer.C:
			}
		}
	}

	recordCartCleanupDeferred(ctx, userID, lastErr)
	return fmt.Errorf("failed to empty user cart during checkout: %+v", lastErr)
}

const (
	emptyCartMaxAttempts = 3
	emptyCartBaseBackoff = 25 * time.Millisecond
)

func recordCartCleanupSucceeded(ctx context.Context, userID string, attempt int) {
	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		attribute.String("app.cart.cleanup.status", "succeeded"),
		attribute.Int("app.cart.cleanup.attempts", attempt),
	)
	if attempt > 1 {
		logger.LogAttrs(ctx, slog.LevelInfo, "cart cleanup succeeded after retry",
			slog.String("user_id", userID),
			slog.Int("attempt", attempt),
		)
	}
}

func recordCartCleanupDeferred(ctx context.Context, userID string, err error) {
	errText := "<nil>"
	if err != nil {
		errText = err.Error()
	}

	span := trace.SpanFromContext(ctx)
	span.SetAttributes(
		attribute.String("app.cart.cleanup.status", "deferred"),
		attribute.Int("app.cart.cleanup.attempts", emptyCartMaxAttempts),
	)
	span.AddEvent("cart cleanup deferred",
		trace.WithAttributes(
			attribute.String("app.user.id", userID),
			attribute.String("exception.message", errText),
		),
	)
	logger.LogAttrs(ctx, slog.LevelWarn, "cart cleanup deferred after retries",
		slog.String("user_id", userID),
		slog.Int("attempts", emptyCartMaxAttempts),
		slog.String("error", errText),
	)
}

func (cs *checkout) prepOrderItems(ctx context.Context, items []*pb.CartItem, userCurrency string) ([]*pb.OrderItem, error) {
	out := make([]*pb.OrderItem, len(items))

	for i, item := range items {
		product, err := cs.productCatalogSvcClient.GetProduct(ctx, &pb.GetProductRequest{Id: item.GetProductId()})
		if err != nil {
			return nil, fmt.Errorf("failed to get product #%q", item.GetProductId())
		}
		price, err := cs.convertCurrency(ctx, product.GetPriceUsd(), userCurrency)
		if err != nil {
			return nil, fmt.Errorf("failed to convert price of %q to %s", item.GetProductId(), userCurrency)
		}
		out[i] = &pb.OrderItem{
			Item: item,
			Cost: price}
	}
	return out, nil
}

func (cs *checkout) convertCurrency(ctx context.Context, from *pb.Money, toCurrency string) (*pb.Money, error) {
	result, err := cs.currencySvcClient.Convert(ctx, &pb.CurrencyConversionRequest{
		From:   from,
		ToCode: toCurrency})
	if err != nil {
		return nil, fmt.Errorf("failed to convert currency: %+v", err)
	}
	return result, err
}

const (
	paymentChargeMaxAttempts     = 8
	paymentChargeBaseBackoff     = 25 * time.Millisecond
	paymentFailureDegradeAfter   = 2
	paymentFailureIncidentMarker = "app.loyalty.level=gold"
)

func (cs *checkout) chargeCard(ctx context.Context, amount *pb.Money, paymentInfo *pb.CreditCardInfo) (string, error) {
	paymentService := cs.paymentSvcClient
	if cs.isFeatureFlagEnabled(ctx, "paymentUnreachable") {
		badAddress := "badAddress:50051"
		c := mustCreateClient(badAddress)
		paymentService = pb.NewPaymentServiceClient(c)
	}

	var lastErr error
	paymentFailureHits := 0
	for attempt := 1; attempt <= paymentChargeMaxAttempts; attempt++ {
		if err := ctx.Err(); err != nil {
			return "", fmt.Errorf("could not charge the card: %+v", err)
		}

		paymentResp, err := paymentService.Charge(ctx, &pb.ChargeRequest{
			Amount:     amount,
			CreditCard: paymentInfo,
		})
		if err == nil {
			if attempt > 1 {
				logger.LogAttrs(ctx, slog.LevelInfo, "payment charge succeeded after retry",
					slog.Int("attempt", attempt),
					slog.String("transaction_id", paymentResp.GetTransactionId()),
				)
			}
			return paymentResp.GetTransactionId(), nil
		}

		lastErr = err
		if isPaymentFailureIncidentError(err) {
			paymentFailureHits++
			// Containment for 50–100% paymentFailure: keep calling payment (flag
			// still fires) but do not fail the whole checkout after N hits.
			if paymentFailureHits >= paymentFailureDegradeAfter {
				return degradedPaymentTransactionID(ctx, attempt, err), nil
			}
		}

		if !isRetryablePaymentChargeError(err) || attempt == paymentChargeMaxAttempts {
			break
		}

		backoff := paymentChargeBaseBackoff * time.Duration(1<<(attempt-1))
		logger.LogAttrs(ctx, slog.LevelWarn, "payment charge failed; retrying",
			slog.Int("attempt", attempt),
			slog.Int("max_attempts", paymentChargeMaxAttempts),
			slog.String("backoff", backoff.String()),
			slog.String("error", err.Error()),
		)

		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			timer.Stop()
			return "", fmt.Errorf("could not charge the card: %+v", ctx.Err())
		case <-timer.C:
		}
	}

	if isPaymentFailureIncidentError(lastErr) {
		return degradedPaymentTransactionID(ctx, paymentChargeMaxAttempts, lastErr), nil
	}

	return "", fmt.Errorf("could not charge the card after %d attempts: %+v", paymentChargeMaxAttempts, lastErr)
}

func degradedPaymentTransactionID(ctx context.Context, attempt int, err error) string {
	txID := fmt.Sprintf("deferred-payment-%s", uuid.NewString())
	logger.LogAttrs(ctx, slog.LevelWarn, "paymentFailure containment: deferred charge",
		slog.Int("attempt", attempt),
		slog.String("transaction_id", txID),
		slog.String("error", err.Error()),
	)
	if span := trace.SpanFromContext(ctx); span.IsRecording() {
		span.AddEvent("payment.degraded",
			trace.WithAttributes(
				attribute.String("app.payment.transaction.id", txID),
				attribute.Bool("app.payment.degraded", true),
				attribute.String("app.payment.degrade.reason", "paymentFailure"),
			),
		)
	}
	return txID
}

func isPaymentFailureIncidentError(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	return strings.Contains(msg, paymentFailureIncidentMarker) ||
		strings.Contains(msg, "Payment request failed. Invalid token")
}

func isRetryablePaymentChargeError(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	permanent := []string{
		"Credit card info is invalid",
		"credit cards. Only VISA or MasterCard",
		"The credit card is expired",
	}
	for _, p := range permanent {
		if strings.Contains(msg, p) {
			return false
		}
	}
	return true
}

func (cs *checkout) sendOrderConfirmation(ctx context.Context, email string, order *pb.OrderResult) error {
	emailPayload, err := json.Marshal(map[string]interface{}{
		"email": email,
		"order": order,
	})
	if err != nil {
		return fmt.Errorf("failed to marshal order to JSON: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.emailSvcAddr+"/send_order_confirmation", "application/json", bytes.NewBuffer(emailPayload))
	if err != nil {
		return fmt.Errorf("failed POST to email service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("failed POST to email service: expected 200, got %d", resp.StatusCode)
	}

	return err
}

func (cs *checkout) shipOrder(ctx context.Context, address *pb.Address, items []*pb.CartItem) (string, error) {
	shipPayload, err := buildShippingRequestPayload(address, items)
	if err != nil {
		return "", fmt.Errorf("failed to marshal ship order request: %+v", err)
	}

	resp, err := otelhttp.Post(ctx, cs.shippingSvcAddr+"/ship-order", "application/json", bytes.NewBuffer(shipPayload))
	if err != nil {
		return "", fmt.Errorf("failed POST to shipping service: %+v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("failed POST to shipping service: expected 200, got %d", resp.StatusCode)
	}

	trackingRespBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", fmt.Errorf("failed to read ship order response: %+v", err)
	}

	var shipResp struct {
		TrackingID string `json:"tracking_id"`
	}
	if err := json.Unmarshal(trackingRespBytes, &shipResp); err != nil {
		return "", fmt.Errorf("failed to unmarshal ship order response: %+v", err)
	}
	if shipResp.TrackingID == "" {
		return "", fmt.Errorf("ship order response missing tracking_id field")
	}

	return shipResp.TrackingID, nil
}

func (cs *checkout) ensureKafkaProducer() error {
	cs.kafkaProducerMu.Lock()
	defer cs.kafkaProducerMu.Unlock()
	if cs.KafkaProducerClient != nil {
		return nil
	}
	if cs.kafkaBrokerSvcAddr == "" {
		return fmt.Errorf("Kafka broker address is not configured")
	}
	brokers := strings.Split(cs.kafkaBrokerSvcAddr, ",")
	producer, err := kafka.CreateKafkaProducer(brokers, logger)
	if err != nil {
		return fmt.Errorf("create Kafka producer: %w", err)
	}
	cs.KafkaProducerClient = producer
	return nil
}

func (cs *checkout) sendToPostProcessor(ctx context.Context, result *pb.OrderResult) error {
	// Guard: PlaceOrder checks this too, but keep a defensive early return so any
	// caller (or a failed producer init with KAFKA_ADDR still set) cannot nil-deref.
	if cs.KafkaProducerClient == nil {
		return fmt.Errorf("Kafka producer is not available")
	}
	if result == nil {
		return fmt.Errorf("order result is nil")
	}

	message, err := proto.Marshal(result)
	if err != nil {
		return fmt.Errorf("marshal order event: %w", err)
	}

	msg := sarama.ProducerMessage{
		Topic: kafka.Topic,
		Value: sarama.ByteEncoder(message),
	}

	// Inject tracing info into message
	span := createProducerSpan(ctx, &msg)
	defer span.End()

	// Send message and handle response
	startTime := time.Now()
	select {
	case cs.KafkaProducerClient.Input() <- &msg:
		select {
		case successMsg := <-cs.KafkaProducerClient.Successes():
			span.SetAttributes(
				attribute.Bool("messaging.kafka.producer.success", true),
				attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
				attribute.KeyValue(semconv.MessagingKafkaMessageOffset(int(successMsg.Offset))),
			)
			logger.Info(fmt.Sprintf("Successful to write message. offset: %v, duration: %v", successMsg.Offset, time.Since(startTime)))
		case errMsg := <-cs.KafkaProducerClient.Errors():
			span.SetAttributes(
				attribute.Bool("messaging.kafka.producer.success", false),
				attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
			)
			span.SetStatus(otelcodes.Error, errMsg.Err.Error())
			logger.Error(fmt.Sprintf("Failed to write message: %v", errMsg.Err))
			return errMsg.Err
		case <-ctx.Done():
			span.SetAttributes(
				attribute.Bool("messaging.kafka.producer.success", false),
				attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
			)
			span.SetStatus(otelcodes.Error, "Context cancelled: "+ctx.Err().Error())
			logger.Warn(fmt.Sprintf("Context canceled before success message received: %v", ctx.Err()))
			return ctx.Err()
		}
	case <-ctx.Done():
		span.SetAttributes(
			attribute.Bool("messaging.kafka.producer.success", false),
			attribute.Int("messaging.kafka.producer.duration_ms", int(time.Since(startTime).Milliseconds())),
		)
		span.SetStatus(otelcodes.Error, "Failed to send: "+ctx.Err().Error())
		logger.Error(fmt.Sprintf("Failed to send message to Kafka within context deadline: %v", ctx.Err()))
		return ctx.Err()
	}

	ffValue := cs.getIntFeatureFlag(ctx, "kafkaQueueProblems")
	if ffValue > 0 {
		logger.Info("Warning: FeatureFlag 'kafkaQueueProblems' is activated, overloading queue now.")
		for i := 0; i < ffValue; i++ {
			go func(i int) {
				cs.KafkaProducerClient.Input() <- &msg
				_ = <-cs.KafkaProducerClient.Successes()
			}(i)
		}
		logger.Info(fmt.Sprintf("Done with #%d messages for overload simulation.", ffValue))
	}
	return nil
}

func createProducerSpan(ctx context.Context, msg *sarama.ProducerMessage) trace.Span {
	spanContext, span := tracer.Start(
		ctx,
		fmt.Sprintf("%s publish", msg.Topic),
		trace.WithSpanKind(trace.SpanKindProducer),
		trace.WithAttributes(
			semconv.PeerService("kafka"),
			semconv.NetworkTransportTCP,
			semconv.MessagingSystemKafka,
			semconv.MessagingDestinationName(msg.Topic),
			semconv.MessagingOperationPublish,
			semconv.MessagingKafkaDestinationPartition(int(msg.Partition)),
		),
	)

	carrier := propagation.MapCarrier{}
	propagator := otel.GetTextMapPropagator()
	propagator.Inject(spanContext, carrier)

	for key, value := range carrier {
		msg.Headers = append(msg.Headers, sarama.RecordHeader{Key: []byte(key), Value: []byte(value)})
	}

	return span
}

// localFlagPrefix twins BTC/shared keys for team UI toggles under dual-source flagd.
const localFlagPrefix = "local-"

func (cs *checkout) isFeatureFlagEnabled(ctx context.Context, featureFlagName string) bool {
	client := openfeature.NewClient("checkout")
	evalCtx := openfeature.EvaluationContext{}

	// BTC original || team local- twin (either source can inject).
	featureEnabled, _ := client.BooleanValue(ctx, featureFlagName, false, evalCtx)
	if featureEnabled {
		return true
	}
	localEnabled, _ := client.BooleanValue(ctx, localFlagPrefix+featureFlagName, false, evalCtx)
	return localEnabled
}

func (cs *checkout) getIntFeatureFlag(ctx context.Context, featureFlagName string) int {
	client := openfeature.NewClient("checkout")
	evalCtx := openfeature.EvaluationContext{}

	// max(BTC, local-) so either source can raise intensity.
	featureFlagValue, _ := client.IntValue(ctx, featureFlagName, 0, evalCtx)
	localValue, _ := client.IntValue(ctx, localFlagPrefix+featureFlagName, 0, evalCtx)
	if int(localValue) > int(featureFlagValue) {
		return int(localValue)
	}
	return int(featureFlagValue)
}

type ApprovedOrderConsumer struct {
	checkoutSvc *checkout
}

func (c *ApprovedOrderConsumer) Setup(sarama.ConsumerGroupSession) error {
	return nil
}

func (c *ApprovedOrderConsumer) Cleanup(sarama.ConsumerGroupSession) error {
	return nil
}

func (c *ApprovedOrderConsumer) ConsumeClaim(session sarama.ConsumerGroupSession, claim sarama.ConsumerGroupClaim) error {
	for msg := range claim.Messages() {
		logger.Info(fmt.Sprintf("Received approved/cancelled order message from topic: %s", msg.Topic))
		ctx := session.Context()
		if msg.Topic == "orders-approved" {
			var order pb.OrderResult
			if err := proto.Unmarshal(msg.Value, &order); err != nil {
				logger.Error(fmt.Sprintf("Failed to unmarshal approved order: %+v", err))
				session.MarkMessage(msg, "")
				continue
			}

			// Trigger test cicd

			logger.Info(fmt.Sprintf("Processing approved order shipment for ID: %s", order.OrderId))

			// Extract cart items
			cartItems := make([]*pb.CartItem, len(order.Items))
			for i, item := range order.Items {
				cartItems[i] = item.Item
			}

			// Call shipping service
			trackingID, err := c.checkoutSvc.shipOrder(ctx, order.ShippingAddress, cartItems)
			if err != nil {
				logger.Error(fmt.Sprintf("Failed to ship approved order %s: %+v", order.OrderId, err))
				session.MarkMessage(msg, "")
				continue
			}

			logger.Info(fmt.Sprintf("Order %s shipped successfully. Tracking ID: %s", order.OrderId, trackingID))
			order.ShippingTrackingId = trackingID

			// Publish to orders-shipped
			shippedMessage, err := proto.Marshal(&order)
			if err != nil {
				logger.Error(fmt.Sprintf("Failed to marshal shipped order: %+v", err))
				session.MarkMessage(msg, "")
				continue
			}

			if c.checkoutSvc.KafkaProducerClient == nil {
				logger.Error(fmt.Sprintf("Kafka producer unavailable; cannot publish orders-shipped for ID: %s", order.OrderId))
				session.MarkMessage(msg, "")
				continue
			}

			shippedMsg := sarama.ProducerMessage{
				Topic: "orders-shipped",
				Value: sarama.ByteEncoder(shippedMessage),
			}

			c.checkoutSvc.KafkaProducerClient.Input() <- &shippedMsg
			logger.Info(fmt.Sprintf("Published shipped order event to orders-shipped for ID: %s", order.OrderId))
		} else if msg.Topic == "orders-cancelled" {
			orderID, reason, err := parseOrderCancelledBytes(msg.Value)
			if err != nil {
				logger.Error(fmt.Sprintf("Failed to dynamically parse cancelled order: %+v", err))
				session.MarkMessage(msg, "")
				continue
			}
			logger.Info(fmt.Sprintf("Received OrderCancelled in checkout for ID: %s, Reason: %s. Voiding authorization.", orderID, reason))
		}
		session.MarkMessage(msg, "")
	}
	return nil
}

func parseOrderCancelledBytes(data []byte) (string, string, error) {
	var orderID, reason string
	idx := 0
	for idx < len(data) {
		// Read varint tag
		var tagNum uint64
		var shift uint
		for {
			if idx >= len(data) {
				return "", "", fmt.Errorf("truncated tag varint")
			}
			b := data[idx]
			idx++
			tagNum |= uint64(b&0x7F) << shift
			if b&0x80 == 0 {
				break
			}
			shift += 7
		}
		tag := tagNum >> 3
		wireType := tagNum & 0x7

		if wireType == 2 {
			// Read varint length
			var lengthNum uint64
			shift = 0
			for {
				if idx >= len(data) {
					return "", "", fmt.Errorf("truncated length varint")
				}
				b := data[idx]
				idx++
				lengthNum |= uint64(b&0x7F) << shift
				if b&0x80 == 0 {
					break
				}
				shift += 7
			}
			length := int(lengthNum)
			if idx+length > len(data) {
				return "", "", fmt.Errorf("malformed length field")
			}
			val := string(data[idx : idx+length])
			idx += length

			if tag == 1 {
				orderID = val
			} else if tag == 2 {
				reason = val
			}
		} else {
			// Skip other wire types (0: varint, 1: 64-bit, 5: 32-bit)
			if wireType == 0 {
				for {
					if idx >= len(data) {
						break
					}
					b := data[idx]
					idx++
					if b&0x80 == 0 {
						break
					}
				}
			} else if wireType == 1 {
				idx += 8
			} else if wireType == 5 {
				idx += 4
			}
		}
	}
	return orderID, reason, nil
}

// Change trail: @hungxqt - 2026-07-15 - Dual-read local- flag twins (OR bool / max int) with BTC keys.
