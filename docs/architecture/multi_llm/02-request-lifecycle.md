# 02 Request Lifecycle

This document visualizes the execution flow of a single LLM request through the orchestration platform. 

## The One Diagram That Matters Most

Every request flows through this uniform pipeline, regardless of the underlying task or chosen provider.

```mermaid
graph TD
    A[Business Service] --> B[LLMService]
    B --> C[LLMRouter]
    C --> D[Resolve Route]
    D --> E[Execution Context Created]
    E --> F[Request Middleware]
    F --> |Capability check, Constraint check, Circuit Breaker| G[Provider Call]
    G --> H[Response Middleware]
    H --> |Cost, Telemetry, Audit| I[Return Response]
    
    F -.->|Short-circuit| H
    G -.->|Exception| H
```

## Sequence Diagrams for Operational Behavior

### 1. Normal Request

```mermaid
sequenceDiagram
    participant Client
    participant LLMService
    participant Router
    participant ReqMW as Request MW
    participant Provider
    participant ResMW as Response MW

    Client->>LLMService: chat(task, request)
    LLMService->>Router: chat(task, request)
    Router->>Router: Resolve primary step
    Router->>Router: Create LLMExecutionContext
    Router->>ReqMW: before_request()
    ReqMW-->>Router: None (proceed)
    Router->>Provider: chat(request)
    Provider-->>Router: LLMResponse
    Router->>ResMW: after_response()
    ResMW-->>Router: LLMResponse
    Router-->>LLMService: LLMResponse
    LLMService-->>Client: LLMResponse
```

### 2. Retry Flow

```mermaid
sequenceDiagram
    participant Router
    participant ReqMW as Request MW
    participant Provider
    participant ResMW as Response MW

    Router->>ReqMW: before_request()
    ReqMW-->>Router: None
    loop Until Success or Max Retries
        Router->>Provider: chat(request)
        Provider-->>Router: ProviderTimeoutError
        Router->>ResMW: on_exception()
        ResMW-->>Router: RetryRequested (via RetryMiddleware)
    end
    Router->>Provider: chat(request)
    Provider-->>Router: LLMResponse
    Router->>ResMW: after_response()
    ResMW-->>Router: LLMResponse
```

### 3. Circuit Breaker Trigger

```mermaid
sequenceDiagram
    participant Router
    participant ReqMW as Request MW
    participant Provider

    Router->>ReqMW: before_request() (CircuitBreakerMiddleware)
    ReqMW-->>Router: raise ProviderUnavailableError
    Note right of Router: Provider skipped completely
    Router->>Router: Catch error, move to fallback step
```

### 4. Fallback Flow

```mermaid
sequenceDiagram
    participant Router
    participant Primary as Primary Provider
    participant Fallback as Fallback Provider
    
    Router->>Primary: call (fails)
    Primary-->>Router: ProviderError
    Router->>Router: fallback_depth++
    Router->>Fallback: call (succeeds)
    Fallback-->>Router: LLMResponse
```
