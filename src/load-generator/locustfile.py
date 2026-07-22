#!/usr/bin/python

# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import os
import random
import uuid
import logging

from locust import HttpUser, task, tag, between
from locust_plugins.users.playwright import PlaywrightUser, pw, PageWithRetry, event

# Durable guard for distributed mode: stale worker messages (HPA scale-down, Spot
# interrupt, pod restart) must not KeyError-kill MasterRunner.client_listener.
# Without this, the master UI shows worker_count=0 until the master process restarts.
def _install_master_stale_worker_guard():
    try:
        from locust.runners import MasterRunner, STATE_RUNNING
    except ImportError:
        return
    if getattr(MasterRunner, "_techx_stale_worker_guard", False):
        return

    _orig_handle_message = MasterRunner.handle_message
    _orig_start = MasterRunner.start

    def _safe_start(self, user_count, spawn_rate):
        try:
            return _orig_start(self, user_count, spawn_rate)
        except ValueError as err:
            logging.warning("Locust start deferred (generator busy): %s", err)
            return None

    def _safe_handle_message(self, client_id, msg):
        msg_type = getattr(msg, "type", None)
        try:
            res = _orig_handle_message(self, client_id, msg)
        except KeyError:
            node_id = getattr(msg, "node_id", None) or client_id
            logging.warning(
                "Ignoring message from unknown/disconnected Locust worker node_id=%s type=%s",
                node_id,
                msg_type,
            )
            res = None

        # Dynamic Load Rebalancing: only rebalance during steady STATE_RUNNING to prevent mid-spawn generator collisions
        if msg_type in ("client_stopped", "client_ready") and getattr(self, "state", None) == STATE_RUNNING:
            target_users = getattr(self, "target_user_count", 0) or 0
            if target_users > 0 and not getattr(self, "_rebalance_scheduled", False):
                self._rebalance_scheduled = True

                def _do_rebalance():
                    try:
                        import gevent
                        gevent.sleep(0.5)
                        if getattr(self, "state", None) == STATE_RUNNING:
                            t_users = getattr(self, "target_user_count", 0) or 0
                            s_rate = getattr(self, "spawn_rate", 10) or 10
                            n_workers = len(getattr(self.clients, "ready", {}))
                            if t_users > 0 and n_workers > 0:
                                logging.info(
                                    "Rebalancing Locust load: %d users across %d active workers...",
                                    t_users, n_workers
                                )
                                self.start(t_users, s_rate)
                    except Exception as err:
                        logging.warning("Locust rebalance deferred: %s", err)
                    finally:
                        self._rebalance_scheduled = False

                try:
                    import gevent
                    gevent.spawn(_do_rebalance)
                except Exception as err:
                    self._rebalance_scheduled = False
                    logging.warning("Failed to schedule Locust rebalance: %s", err)
        return res

    MasterRunner.handle_message = _safe_handle_message
    MasterRunner.start = _safe_start
    MasterRunner._techx_stale_worker_guard = True


_install_master_stale_worker_guard()


from opentelemetry import context, baggage, trace
from opentelemetry.context import Context
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.jinja2 import Jinja2Instrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from openfeature import api
from openfeature.contrib.provider.ofrep import OFREPProvider
from openfeature.contrib.hook.opentelemetry import TracingHook

from playwright.async_api import Route, Request

# Configure tracer provider first (needed for trace context in logs)
tracer_provider = TracerProvider()
trace.set_tracer_provider(tracer_provider)
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

# Configure logger provider with the same resource
logger_provider = LoggerProvider()
set_logger_provider(logger_provider)

# Set up log exporter and processor
log_exporter = OTLPLogExporter()
logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))

# Create logging handler that will include trace context
handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)

# Configure root logger
root_logger = logging.getLogger()
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

# Configure metrics
metric_exporter = OTLPMetricExporter()
set_meter_provider(MeterProvider([PeriodicExportingMetricReader(metric_exporter)]))

# Instrument logging to automatically inject trace context
LoggingInstrumentor().instrument(set_logging_format=True)

# Instrumenting manually to avoid error with locust gevent monkey
Jinja2Instrumentor().instrument()
RequestsInstrumentor().instrument()
SystemMetricsInstrumentor().instrument()
URLLib3Instrumentor().instrument()

logging.info("Instrumentation complete - logs will now include trace context")

# Initialize Flagd provider
base_url = f"http://{os.environ.get('FLAGD_HOST', 'localhost')}:{os.environ.get('FLAGD_OFREP_PORT', 8016)}"
api.set_provider(OFREPProvider(base_url=base_url))
api.add_hooks([TracingHook()])

def _read_integer_flag(client, flag_key: str, default: int = 0) -> int:
    """Read one integer flag; fail closed to default on any evaluation error.

    openfeature-sdk evaluate_flag_details can raise UnboundLocalError for
    flag_evaluation when a BaseException (gevent Timeout / GreenletExit under
    Locust) escapes before the local is assigned and the finally block runs.
    Flood traffic must not fail the Locust task when flagd/OFREP is flaky.
    """
    try:
        value = client.get_integer_value(flag_key, default)
        if value is None:
            return default
        return int(value)
    except Exception as err:
        logging.warning(
            "flagd integer evaluation failed for key=%s; using default=%s (%s: %s)",
            flag_key,
            default,
            type(err).__name__,
            err,
        )
        return default


def get_flagd_value(FlagName):
    # BTC original + team local- twin: max so either source can inject.
    client = api.get_client()
    btc = _read_integer_flag(client, FlagName, 0)
    local = _read_integer_flag(client, f"local-{FlagName}", 0)
    return max(btc, local)

categories = [
    "binoculars",
    "telescopes",
    "accessories",
    "assembly",
    "travel",
    "books",
    None,
]

products = [
    "0PUK6V6EV0",
    "1YMWWN1N4O",
    "2ZYFJ3GM2N",
    "66VCHSJNUP",
    "6E92ZMYYFZ",
    "9SIQT8TOJO",
    "L9ECAV7KIM",
    "LS4PSXUNUM",
    "OLJCESPC7Z",
    "HQTGWGPNH4",
]

people_file = open('people.json')
people = json.load(people_file)

class WebsiteUser(HttpUser):
    # Keep HTTP traffic dominant; browser (Playwright) users are much heavier.
    weight = int(os.environ.get("LOCUST_HTTP_USER_WEIGHT", "9"))
    wait_time = between(1, 10)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tracer = trace.get_tracer(__name__)

    @task(1)
    def index(self):
        with self.tracer.start_as_current_span("user_index", context=Context()):
            logging.info("User accessing index page")
            self.client.get("/")

    @task(10)
    def browse_product(self):
        product = random.choice(products)
        with self.tracer.start_as_current_span("user_browse_product", context=Context(), attributes={"product.id": product}):
            logging.info(f"User browsing product: {product}")
            self.client.get("/api/products/" + product)

    @task(3)
    def get_recommendations(self):
        product = random.choice(products)
        with self.tracer.start_as_current_span("user_get_recommendations", context=Context(), attributes={"product.id": product}):
            logging.info(f"User getting recommendations for product: {product}")
            params = {
                "productIds": [product],
            }
            self.client.get("/api/recommendations", params=params)

    @task(2)
    def get_product_reviews(self):
        product = random.choice(products)
        with self.tracer.start_as_current_span("user_get_product_reviews", context=Context(), attributes={"product.id": product}):
            logging.info(f"User getting product reviews for product: {product}")
            self.client.get("/api/product-reviews/" + product)

    @tag("ai")
    @task(1)
    def ask_product_ai_assistant(self):
        product = random.choice(products)
        question = 'Can you summarize the product reviews?'
        with self.tracer.start_as_current_span("user_ask_product_ai_assistant", context=Context(), attributes={"product.id": product, "question": question}):
            logging.info(f"Asking the AI Assistant a question for: {product} {question}")
            question = {
                "question": question
            }
            self.client.post("/api/product-ask-ai-assistant/" + product, json=question)

    @task(3)
    def get_ads(self):
        category = random.choice(categories)
        with self.tracer.start_as_current_span("user_get_ads", context=Context(), attributes={"category": str(category)}):
            logging.info(f"User getting ads for category: {category}")
            params = {
                "contextKeys": [category],
            }
            self.client.get("/api/data/", params=params)

    @task(3)
    def view_cart(self):
        with self.tracer.start_as_current_span("user_view_cart", context=Context()):
            logging.info("User viewing cart")
            self.client.get("/api/cart")

    @task(2)
    def add_to_cart(self, user=""):
        if user == "":
            user = str(uuid.uuid4())
        product = random.choice(products)
        quantity = random.choice([1, 2, 3, 4, 5, 10])
        with self.tracer.start_as_current_span("user_add_to_cart", context=Context(), attributes={"user.id": user, "product.id": product, "quantity": quantity}):
            logging.info(f"User {user} adding {quantity} of product {product} to cart")
            self.client.get("/api/products/" + product)
            cart_item = {
                "item": {
                    "productId": product,
                    "quantity": quantity,
                },
                "userId": user,
            }
            self.client.post("/api/cart", json=cart_item)

    @task(1)
    def checkout(self):
        user = str(uuid.uuid4())
        with self.tracer.start_as_current_span("user_checkout_single", context=Context(), attributes={"user.id": user}):
            self.add_to_cart(user=user)
            checkout_person = random.choice(people)
            checkout_person["userId"] = user
            self.client.post("/api/checkout", json=checkout_person)
            logging.info(f"Checkout completed for user {user}")

    @task(1)
    def checkout_multi(self):
        user = str(uuid.uuid4())
        item_count = random.choice([2, 3, 4])
        with self.tracer.start_as_current_span("user_checkout_multi", context=Context(),
                                            attributes={"user.id": user, "item.count": item_count}):
            for i in range(item_count):
                self.add_to_cart(user=user)
            checkout_person = random.choice(people)
            checkout_person["userId"] = user
            self.client.post("/api/checkout", json=checkout_person)
            logging.info(f"Multi-item checkout completed for user {user}")

    @task(5)
    def flood_home(self):
        flood_count = get_flagd_value("loadGeneratorFloodHomepage")
        if flood_count > 0:
            with self.tracer.start_as_current_span("user_flood_home",  context=Context(), attributes={"flood.count": flood_count}):
                logging.info(f"User flooding homepage {flood_count} times")
                for _ in range(0, flood_count):
                    self.client.get("/")

    def on_start(self):
        with self.tracer.start_as_current_span("user_session_start", context=Context()):
            session_id = str(uuid.uuid4())
            logging.info(f"Starting user session: {session_id}")
            ctx = baggage.set_baggage("session.id", session_id)
            ctx = baggage.set_baggage("synthetic_request", "true", context=ctx)
            context.attach(ctx)
            self.index()


browser_traffic_enabled = os.environ.get("LOCUST_BROWSER_TRAFFIC_ENABLED", "").lower() in ("true", "yes", "on")

if browser_traffic_enabled:
    class WebsiteBrowserUser(PlaywrightUser):
        weight = int(os.environ.get("LOCUST_BROWSER_USER_WEIGHT", "1"))
        headless = True  # to use a headless browser, without a GUI

        # IMPORTANT: Do not set instance attrs in __init__ after super().__init__().
        # PlaywrightUser.__init__ does copy.copy(self) into sub_users *before* this
        # subclass body would run post-super assignments. Tasks execute on those
        # copies, so attrs like self.tracer would be missing and every TASK fails
        # with AttributeError (near-zero response time, 100% fail rate).

        @task
        @pw
        async def open_cart_page_and_change_currency(self, page: PageWithRetry):
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("browser_change_currency", context=Context()):
                try:
                    page.on("console", lambda msg: print(msg.text))
                    await page.route('**/*', add_baggage_header)
                    await page.goto("/cart", wait_until="domcontentloaded")
                    await page.select_option('[name="currency_code"]', 'CHF')
                    await page.wait_for_timeout(2000)  # giving the browser time to export the traces
                    logging.info("Currency changed to CHF")
                except Exception as e:
                    logging.error(f"Error in change currency task: {str(e)}")

        @task
        @pw
        async def add_product_to_cart(self, page: PageWithRetry):
            tracer = trace.get_tracer(__name__)
            with tracer.start_as_current_span("browser_add_to_cart", context=Context()):
                try:
                    page.on("console", lambda msg: print(msg.text))
                    await page.route('**/*', add_baggage_header)
                    await page.goto("/", wait_until="domcontentloaded")
                    # Product cards are client-rendered; wait for catalog image XHR
                    # before clicking so we do not race empty product list.
                    await page.wait_for_event(
                        "response",
                        predicate=lambda r: "/images/products/RoofBinoculars.jpg" in r.url and r.status == 200,
                        timeout=15000,
                    )
                    await page.click('p:has-text("Roof Binoculars")')
                    await page.wait_for_load_state("domcontentloaded")
                    await page.click('button:has-text("Add To Cart")')
                    await page.wait_for_load_state("domcontentloaded")
                    await page.wait_for_timeout(2000)  # giving the browser time to export the traces
                    logging.info("Product added to cart successfully")
                except Exception as e:
                    logging.error(f"Error in add to cart task: {str(e)}")

async def add_baggage_header(route: Route, request: Request):
    existing_baggage = request.headers.get('baggage', '')
    headers = {
        **request.headers,
        'baggage': ', '.join(filter(None, (existing_baggage, 'synthetic_request=true')))
    }
    await route.continue_(headers=headers)

# Change trail: @hungxqt - 2026-07-19 - Fail-closed flagd integer reads to avoid OpenFeature UnboundLocalError under Locust.
