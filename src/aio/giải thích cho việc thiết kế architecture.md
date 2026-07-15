```mermaid
flowchart TD
	subgraph inject["1 - Thu thập hoặc nhận tín hiệu"]
	    A["Prometheus polling<br/>registered query IDs"]
	    G["Grafana hard-rule webhook"]
	end
	
	A["Prometheus polling<br/>registered query IDs"] --> B["Signal qualification gate"]
	G["Grafana hard-rule webhook"] --> B
	
    B -->|verified| C["Normalize labels, units, windows"]
    B -->|missing/stale/invalid| N["Monitoring-data incident<br/>UNKNOWN, not healthy"]

	subgraph anomaly_detection["5 - Detector engine"]
	    E1["Official SLO detector"]
	    E2["No-data detector"]
	    E3["Dependency / DB / anomaly detectors"]
	    E1 --> F["Candidate event"]
	    E2 --> F
	    E3 --> F	    
	end

    C --> D["Feature builder<br/>24h SLO, 5m/15m diagnostics,<br/>median/MAD/EWMA"]
    D --> E1["Official SLO detector"]
    D --> E2["No-data detector"]
    D --> E3["Dependency / DB / anomaly detectors"]


    N --> I["Incident manager"]
    
    F --> H["Correlation + likely dependency ranking"]
    H --> J["On-demand enrichment"]
    
	subgraph enrichment["7 - on-demand enrichment"]
	    J --> J1["Jaeger trace summary"]
	    J --> J2["OpenSearch bounded log excerpts"]
	    J --> J3["Kubernetes readiness/restart/replica status"]
    end

    J1 --> I
    J2 --> I
    J3 --> I
    H --> I

    I --> K["Deduplicate / update timeline"]
    K --> L["Attach canonical runbook"]
    
    subgraph dedup["9 - Deduplicate, attach runbook, notify"]
		K["Deduplicate / update timeline"]
		L["Attach canonical runbook"]
    end
    
    L --> M["Notification outbox"]
    M --> O["TF2 on-call channel"]

    L --> P["Policy + remediation engine"]
    P -->|default| Q["Dry-run recommendation<br/>no mutation"]
    P -->|blocked| R["Escalate with reason"]
    P -.->|optional only after ADR-LIVE-001| S["Separate live executor boundary"]

    subgraph policy["10 - Policy + remediation engine"]
		P["Policy + remediation engine"]
		Q["Dry-run recommendation<br/>no mutation"]
		R["Escalate with reason"]
		S["Separate live executor boundary"]
    end


    Q --> T["Verification queries"]
    R --> T
    S -.-> T

    T -->|fresh consecutive pass| U["Resolve + audit"]
    T -->|missing/stale/fail| V["Escalate / rollback if predefined"]

    I --> W["SQLite WAL PVC<br/>incident + audit state"]
    U --> W
    V --> W
```

[[1. Thu thập hoặc nhận tín hiệu]] (phần [[Grafana hard-rule webhook]] có thêm 1 luồn nối trực tiếp tới Alert)
[[2. Signal qualification gate]]
[[3. Normalize dữ liệu]]
[[4. Feature builder]]
[[5. Detector engine]]
[[6. Correlation và likely dependency ranking]]
[[7. On-demand enrichment]] (phần này sẽ lấy thêm những nguồn dữ liệu như logs, K8s logs,... để làm giàu thêm thông tin để mô hình có thể cải thiện cũng như là chắc chắn quyết định của mình hơn)
[[8. Incident manager]]
[[9. Deduplicate, attach runbook, notify]]
[[10. Policy + remediation engine]] (giải thích lại phần này)
[[11. Verification]]
[[12. SQLite WAL PVC]]

