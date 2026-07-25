# CDO Runtime Topology

Nguồn chính: `aio/config/runtime.json`.

```mermaid
flowchart LR
  classDef app fill:#e8f3ff,stroke:#2364aa,color:#102a43
  classDef external fill:#fff4d6,stroke:#b7791f,color:#3d2c00
  classDef observability fill:#edf2f7,stroke:#4a5568,color:#1a202c
  classDef protected fill:#ffe8e8,stroke:#c53030,color:#3b0d0c

  subgraph prod["techx-corp-prod"]
    load_generator["load-generator<br/>Deployment<br/>testing"]:::protected
    frontend_proxy["frontend-proxy<br/>Deployment<br/>edge"]:::app
    frontend["frontend<br/>Deployment<br/>web"]:::app
    image_provider["image-provider<br/>Deployment<br/>web"]:::app

    checkout["checkout<br/>Deployment<br/>checkout"]:::app
    payment["payment<br/>Deployment<br/>checkout"]:::app
    cart["cart<br/>Deployment<br/>checkout"]:::app
    currency["currency<br/>Deployment<br/>checkout"]:::app
    shipping["shipping<br/>Deployment<br/>checkout"]:::app
    email["email<br/>Deployment<br/>checkout"]:::app
    quote["quote<br/>Deployment<br/>checkout"]:::app
    fraud_detection["fraud-detection<br/>Deployment<br/>checkout"]:::app
    accounting["accounting<br/>Deployment<br/>checkout"]:::app

    product_catalog["product-catalog<br/>Deployment<br/>catalog"]:::app
    product_reviews["product-reviews<br/>Deployment<br/>catalog"]:::app
    recommendation["recommendation<br/>Deployment<br/>recommendation"]:::app
    ad["ad<br/>Deployment<br/>platform"]:::app
    shopping_copilot["shopping-copilot<br/>Deployment<br/>shopping-copilot"]:::app
    llm["llm<br/>Deployment<br/>catalog"]:::app

    flagd["flagd<br/>Deployment<br/>platform"]:::protected
    jaeger["jaeger<br/>Deployment<br/>observability"]:::protected
    otel_collector["otel-collector<br/>DaemonSet<br/>observability"]:::observability
    opensearch["opensearch<br/>StatefulSet<br/>observability"]:::protected
  end

  subgraph external["external"]
    kafka["kafka<br/>ManagedService<br/>platform"]:::external
    postgresql["postgresql<br/>Database<br/>data"]:::protected
    valkey_cart["valkey-cart<br/>Database<br/>checkout"]:::protected
    external_llm["external-llm<br/>ExternalAPI<br/>catalog"]:::external
    aws_bedrock["aws-bedrock<br/>ExternalAPI<br/>shopping-copilot"]:::external
  end

  load_generator --> frontend_proxy
  load_generator --> flagd

  frontend_proxy --> frontend
  frontend_proxy --> image_provider

  frontend --> product_catalog
  frontend --> product_reviews
  frontend --> recommendation
  frontend --> checkout
  frontend --> cart
  frontend --> ad
  frontend --> currency
  frontend --> shipping
  frontend --> shopping_copilot
  frontend --> flagd

  checkout --> cart
  checkout --> currency
  checkout --> product_catalog
  checkout --> shipping
  checkout --> payment
  checkout --> email
  checkout --> kafka
  checkout --> flagd

  payment --> flagd
  cart --> flagd
  cart --> valkey_cart
  shipping --> quote
  fraud_detection --> flagd
  fraud_detection --> kafka
  fraud_detection --> valkey_cart
  accounting --> kafka
  accounting --> postgresql

  product_catalog --> postgresql
  product_catalog --> flagd
  product_reviews --> product_catalog
  product_reviews --> postgresql
  product_reviews --> flagd
  product_reviews --> llm
  product_reviews --> external_llm
  recommendation --> product_catalog
  recommendation --> flagd
  ad --> flagd
  image_provider --> flagd
  llm --> flagd

  shopping_copilot --> product_catalog
  shopping_copilot --> product_reviews
  shopping_copilot --> cart
  shopping_copilot --> valkey_cart
  shopping_copilot --> aws_bedrock
```

## Validation

- Runtime topology hiện có 28 services và 48 dependency edges.
- Không có dependency trỏ tới service không tồn tại.
- Không có self-dependency.
- Không có duplicate service name.
- `TopologyGraph` regression hiện kiểm tra các edge trọng yếu: `checkout -> payment`, `frontend -> shipping`, `shipping -> quote`, `payment` blast radius, `accounting`, `fraud-detection`, `product-reviews`, `shopping-copilot`.

## Accuracy Notes

- File này phản ánh runtime topology dùng cho AIOps RCA/remediation, không phải full observability graph.
- `aio/docs/operations/topology/platform-topology.graph.json` là artifact rộng hơn, có thêm `grafana`, `prometheus`, `aiops-runtime`, `aiops-state`, `kubernetes-api`, `tf2-oncall-channel`, `flagd-ui`, `cdo-cost-snapshot`, và observability edges.
- Runtime topology có các node/edge mới hơn artifact rộng: `shopping-copilot`, `aws-bedrock`, `external-llm`, cùng các dependency AI path của `shopping-copilot`.
- Vì vậy độ chính xác runtime hiện ổn cho RCA path; artifact rộng nên được refresh nếu muốn dùng nó làm bản đồ CDO tổng.
