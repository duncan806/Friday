# Friday 구현 상세 명세 (Implementation Spec)

> 대상 독자: 이 저장소를 실제로 빌드/확장하는 엔지니어.
> 전제 설계: [`design-gpt-claude-dialogue.md`](./design-gpt-claude-dialogue.md).
> 목표 규모: 얇은 오케스트레이터가 아니라 **강제 커널 + 대화 엔진 + 실행 엔진 +
> 이벤트 버스 + 어댑터 + 관측성**을 갖춘 이중 모드(validate/collaborate) 시스템.
> 기존 코드는 폐기가 아니라 **각 서브시스템의 씨앗**으로 승격한다(매핑은 §2.3).

---

## 0. 한 문장 명세

> **사람은 Claude(느린 통찰)와 지속 대화하고, GPT(빠른 실행)는 배경에서 계속
> 일하며, 두 지능의 역할 경계는 프롬프트가 아니라 커널이 구조로 강제한다.**

이 문장의 네 절이 그대로 네 서브시스템이 된다: 대화 엔진 · 실행 엔진 · 라우팅 ·
강제 커널. 나머지(버스/어댑터/관측성/표면)는 이 넷을 잇는 배관이다.

---

## 1. 아키텍처 개요

```
                        ┌──────────────────────────────────────────┐
   사람 ⇄ 대화 ────────▶│  Conversation Engine   (친: friday.convo)  │
                        │  세션·턴·스트리밍·요약메모리                 │
                        └───────────────┬──────────────────────────┘
                                        │ Directive (방향/판단/중단)
                                        ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  Kernel  (친: friday.kernel)                                     │
   │  · Authority: 판단권 게이트(누가 무엇을 결정할 수 있나)            │
   │  · Integrity: 경계 assert (validate=정보, collaborate=역할)       │
   │  · Mode:      validate | collaborate 정책 주입                    │
   └───────────────┬────────────────────────────────┬───────────────┘
                   │ 승인된 Directive                 │ 강제 규칙
                   ▼                                  ▼
   ┌───────────────────────────────┐   ┌──────────────────────────────┐
   │ Execution Engine              │   │ Router / Triggers            │
   │ (친: friday.exec — orchestr.  │   │ (친: friday.route)           │
   │  진화). GPT 라운드 루프,       │◀─▶│ Claude를 언제 부를지 규칙      │
   │  자가수정, 빌드, 커밋          │   │ (build_fail/checkin/사람요청)  │
   └───────────────┬───────────────┘   └──────────────────────────────┘
                   │ 상태/이벤트
                   ▼
   ┌────────────────────────────────────────────────────────────────┐
   │  Event Bus  (친: friday.bus) — 모든 상태 변화를 파일로 물질화     │
   │  events.jsonl (append-only) + status.json (스냅샷) + flags/       │
   └───────────────┬────────────────────────────────┬───────────────┘
                   ▼                                  ▼
   ┌───────────────────────────┐        ┌───────────────────────────┐
   │ Provider Adapters         │        │ Surface                   │
   │ (친: friday.providers)    │        │ TUI / Dashboard / HTTP    │
   │ claude·codex·gh 능력탐지   │        │ (친: friday.tui/.web)     │
   └───────────────────────────┘        └───────────────────────────┘
```

핵심 불변식(모든 계층 공통):

- **파일이 진실의 원천(source of truth).** 프로세스는 재시작 가능해야 하고, 상태는
  전부 파일에서 복원된다(기존 `_restore_state` 철학 확장). 인메모리는 캐시일 뿐.
- **커널을 우회하는 경로는 없다.** 대화 엔진도 실행 엔진도 Directive를 커널에
  통과시키지 않고 상대에게 전달할 수 없다.
- **모든 모델 호출은 어댑터를 지난다.** 직접 `subprocess`로 CLI를 부르는 코드 금지
  (기존 `CLIAgents`/`natural.interpret`를 어댑터로 흡수).

---

## 2. 모듈 인벤토리 & 기존 코드 매핑

### 2.1 패키지 레이아웃 (목표)

```
src/friday/
  __init__.py
  __main__.py
  cli.py                 # 런처/서브커맨드 (기존 확장)
  config.py          ★  # 스키마·검증·기본값 (기존 DEFAULT_CONFIG 승격)
  errors.py          ★  # 예외 계층 (IntegrityBreach 등 통합)

  kernel/            ★  # 강제 커널
    __init__.py
    authority.py         # 판단권 게이트
    integrity.py         # 경계 assert (기존 integrity.py 흡수·확장)
    mode.py              # validate/collaborate 정책

  convo/             ★  # 대화 엔진 (사람 ⇄ Claude)
    __init__.py
    session.py           # 대화 세션·턴 기록·재개
    engine.py            # 턴 루프·스트리밍
    memory.py            # 요약 메모리(기존 ContextManager 재사용)
    directive.py         # 대화 결론 → Directive 추출

  exec/                  # 실행 엔진 (GPT 워커) — 기존 orchestrator.py 진화
    __init__.py
    engine.py            # run_cycle/run_round 승격
    round.py             # 단일 라운드 파이프라인
    filters.py           # forward/reverse 필터 (기존 bandwidth_filter 흡수)
    gitsnap.py           # 라운드 커밋 (기존 gitutil.py)

  route/             ★  # 라우팅/트리거
    __init__.py
    triggers.py          # Claude 호출 트리거 규칙
    router.py            # Directive 분배

  bus/               ★  # 이벤트 버스
    __init__.py
    events.py            # 이벤트 타입·직렬화
    log.py               # events.jsonl append/tail
    status.py            # status.json 스냅샷 (기존 write_status 흡수)
    flags.py             # start/stop/pause 플래그 파일

  providers/         ★  # 어댑터
    __init__.py
    base.py              # Adapter 프로토콜·능력탐지
    claude.py            # Claude CLI 어댑터 (기존 CLIAgents.claude)
    codex.py             # Codex CLI 어댑터 (기존 CLIAgents.codex)
    github.py            # gh 어댑터 (기존 integrations.py)
    routing_llm.py       # 자연어 의도 분류 (기존 natural.py)

  tui/                   # 터미널 표면 (기존 tui.py 분해)
    __init__.py
    app.py               # 이벤트 루프
    convo_view.py        # 대화 뷰
    cycle_view.py        # 실행 상태 뷰
  web/                   # 대시보드/HTTP (기존 dashboard_gen.py + control_server.py)
    __init__.py
    dashboard.py
    server.py
  data/                  # 프롬프트·폰트·스프라이트 (기존)
```

★ = 신규 서브시스템. 나머지는 기존 파일의 승격.

### 2.2 규모 감각 (왜 AutoGen급 이상인가)

| 서브시스템 | 신규/승격 | 대략 LOC | 성격 |
|---|---|---|---|
| kernel | 신규 | 500–800 | 판단권·모드·강제 assert |
| convo | 신규 | 700–1000 | 세션·스트리밍·메모리·directive |
| exec | 승격 | 600–900 | 라운드 파이프라인·필터·커밋 |
| route | 신규 | 300–500 | 트리거·분배 |
| bus | 신규 | 400–600 | 이벤트·로그·스냅샷·플래그 |
| providers | 승격 | 500–800 | 어댑터·능력탐지·failover |
| tui/web | 승격 | 900–1300 | 두 표면 |
| config/errors | 신규 | 200–300 | 스키마·예외계층 |
| tests | 신규 | 1500+ | 단위·통합·속성 |
| **합계** | | **≈ 6000–8000** | 얇은 스크립트가 아님 |

AutoGen과의 차이는 LOC가 아니라 **강제 커널의 존재**다. AutoGen/CrewAI는 역할이
프롬프트 규약이지만 Friday는 커널이 코드로 강제한다(§6, §8).

### 2.3 기존 → 목표 매핑 (마이그레이션 원장)

| 기존 | 이동/흡수 | 비고 |
|---|---|---|
| `orchestrator.CLIAgents` | `providers/claude.py`, `providers/codex.py` | 어댑터화 |
| `orchestrator.Orchestrator` | `exec/engine.py` | run_cycle/run_round 승격 |
| `orchestrator.parse_claude_attempt` | `exec/round.py` | 그대로 |
| `integrity.py` (3 assert) | `kernel/integrity.py` | + 역채널 assert 추가 |
| `bandwidth_filter.py` | `exec/filters.py` (forward) | + reverse 필터 신설 |
| `context.py` | `convo/memory.py` + `exec/round.py` | 공유 |
| `natural.py` | `providers/routing_llm.py` | 어댑터 failover 재사용 |
| `dashboard_gen.py` | `web/dashboard.py` | 그대로 |
| `control_server.py` | `web/server.py` | **보안 패치 필수**(§9) |
| `gitutil.py` | `exec/gitsnap.py` | 그대로 |
| `cli.py` `write_status` 호출부 | `bus/status.py` | 단일화 |

---

## 3. 도메인 모델 & 상태

모든 상태는 dataclass로 정의하고 파일로 직렬화한다. 인메모리 타입:

```python
# convo/session.py
@dataclass
class Turn:
    role: str            # "human" | "claude"
    text: str
    ts: str              # ISO8601 (외부 주입, §12 clock)
    directive_id: str | None = None   # 이 턴이 낳은 Directive

@dataclass
class ConversationState:
    session_id: str
    turns: list[Turn] = field(default_factory=list)
    summary: str = ""            # 오래된 턴 압축 (memory)
    open_directives: list[str] = field(default_factory=list)

# route/router.py
@dataclass
class Directive:
    id: str
    kind: str            # "steer" | "halt" | "resume" | "redesign" | "verdict" | "noop"
    text: str            # GPT/실행엔진에 주입될 방향 (필터 통과본)
    origin: str          # "human+claude" | "trigger" | "human"
    ts: str
    applied_round: int | None = None

# exec/engine.py (기존 RoundResult/CycleState 승격)
@dataclass
class RoundResult:
    round: int
    blocked: bool
    deviation: bool
    quadrant: str
    void: bool = False
    build_failed: bool = False
    dropped_count: int = 0
    directive_id: str | None = None   # 이 라운드에 적용된 방향

@dataclass
class CycleState:
    rounds: list[RoundResult] = field(default_factory=list)
    status: str = "running"
    context: dict = field(default_factory=dict)
    mode: str = "validate"
```

### 3.1 온디스크 레이아웃 (cycle data, `friday init`가 생성)

```
<workspace-root>/
  config.yaml
  status.json                 # 스냅샷 (표면이 폴링)
  events.jsonl                # append-only 이벤트 로그 (감사·복원)
  task/task.md
  workspace/                  # git repo (Codex가 빌드)
    src/  surface/
  reports/round_NNN.md        # forward 필터 통과본
  reports/dropped/round_NNN.md
  questions/round_NNN_tK.md ★ # 역채널: Codex→Claude 질문 (A안)
  answers/round_NNN_tK.md   ★ # 역채널: Claude→Codex 답변
  predictions/round_NNN.md
  convo/session_SSS.jsonl   ★ # 사람⇄Claude 대화 로그
  directives/dir_XXX.json   ★ # 발효된 방향
  verdicts/verdict_NNN.json
  flags/  {start,stop,pause}.flag
  context.json                # 실행 컨텍스트 예산 상태
```

원칙: **`reports/`가 canonical(기존과 동일).** `status.json`/`events.jsonl`은 파생.
크래시 후 `events.jsonl` 재생 + `reports/` 스캔으로 완전 복원(§14).

---

## 4. 이벤트 버스 & 파일 프로토콜

### 4.1 이벤트

```python
# bus/events.py
EVENT_KINDS = (
    "boot", "check", "task_planted",
    "round_started", "round_done", "build_failed", "integrity_breach",
    "question_asked", "answer_given",           # A안 역채널
    "human_turn", "claude_turn",                # 대화
    "directive_issued", "directive_applied",
    "cycle_status", "notify",
)

@dataclass
class Event:
    kind: str
    ts: str
    payload: dict
```

### 4.2 로그 (append-only, 원자적)

```python
# bus/log.py
class EventLog:
    def __init__(self, root: Path): ...
    def append(self, ev: Event) -> None:
        # events.jsonl 에 한 줄 append. fsync 후 리턴. 파일 락(§15).
    def tail(self, since: int = 0) -> Iterator[Event]:
        # 표면이 증분 폴링. since = 바이트 오프셋 또는 seq.
    def replay(self) -> Iterator[Event]:
        # 복원용 전체 재생.
```

`status.json`은 `bus/status.py`가 이벤트를 접어(fold) 만드는 **스냅샷**이다
(기존 `write_status` 흡수). 표면은 우선 `events.jsonl`을 tail하고, 콜드스타트에서만
스냅샷을 읽는다.

### 4.3 플래그 (제어 신호)

기존 `stop.flag`/`start.flag` 확장: `flags/{start,stop,pause,resume}.flag`.
`bus/flags.py`가 원자적 생성/소비. 실행 엔진과 워처가 매 라운드 전 확인.

---

## 5. 대화 엔진 (사람 ⇄ Claude)

### 5.1 세션

```python
# convo/session.py
class Session:
    def __init__(self, root: Path, session_id: str): ...
    def load(self) -> ConversationState:        # convo/session_SSS.jsonl 복원
    def append_turn(self, turn: Turn) -> None:   # append + 이벤트 발행
    def state(self) -> ConversationState:
```

### 5.2 턴 루프

```python
# convo/engine.py
class ConversationEngine:
    def __init__(self, root, kernel, providers, memory, bus): ...

    def human_says(self, text: str) -> Directive | None:
        """사람 입력 → (필요시) Claude 호출 → 응답 스트리밍 → Directive 추출.
        1. Turn(human) 기록·이벤트.
        2. 메모리에서 컨텍스트 구성 (요약 + 최근 턴 + 실행 상태 요약).
        3. Claude 어댑터 호출 (스트리밍) → Turn(claude) 기록.
        4. directive.extract(응답) → Directive|None.
        5. Directive는 커널 승인 후에만 라우터로(§7). 미승인 시 대화만 남고 실행 무변.
        """

    def stream(self) -> Iterator[str]:
        """표면이 소비할 토큰 스트림 (claude 어댑터의 스트리밍 패스스루)."""
```

핵심: **대화는 실행을 직접 건드리지 않는다.** 오직 Directive를 낳고, Directive는
커널을 통과해야 실행 엔진에 닿는다. 이것이 "양보 불가한 판단권"의 물리적 위치다.

### 5.3 메모리 (기존 ContextManager 재사용)

```python
# convo/memory.py
class ConversationMemory:
    def __init__(self, root, budget_chars, recent_turns): ...
    def build(self, state: ConversationState, exec_summary: str) -> str:
        # [요약] + [최근 K턴] + [실행상태 요약(라운드/막힘/빌드)] 를 예산 내로.
        # 기존 ContextManager.build 의 압축/클리핑 로직 공유 —
        # 단, 클리핑은 **턴 경계에서** (design 리뷰 Medium#5 수정 반영).
```

---

## 6. 실행 엔진 (GPT 워커) — orchestrator 진화

기존 `Orchestrator.run_round` 파이프라인(a예측→b시도→c필터→d빌드→e대시보드)을
유지하되, 다음을 추가한다:

1. **Directive 주입점.** 라운드 시작 시 `route.pending_directive()`를 읽어 Codex
   프롬프트에 방향으로 병합. `RoundResult.directive_id`에 기록.
2. **연속 가동(collaborate).** `pause.flag`가 없고 `halt` Directive가 없는 한
   라운드를 계속 돈다(사람을 기다리지 않음). validate 모드는 기존처럼
   `awaiting verdict`에서 정지.
3. **A안 역채널(옵션, `dialogue_turns>0`).** c필터 후 d빌드 전에 Codex↔Claude
   왕복 K턴(설계 §2.4 스케치). forward/reverse 필터·역채널 assert 적용.

```python
# exec/engine.py
class ExecutionEngine:
    def __init__(self, root, kernel, providers, filters, bus, router): ...
    def run_round(self, n: int) -> RoundResult: ...   # 기존 로직 + 위 3점
    def run_cycle(self) -> CycleState: ...            # 기존 + pause/directive 인지
```

### 6.1 필터 (기존 bandwidth_filter + 신규 reverse)

```python
# exec/filters.py
def forward_filter(report: dict, level: int) -> tuple[dict, list[str]]:
    # 기존 apply_filter 그대로 (Claude→Codex: intent/Why 제거).

def reverse_filter(text: str) -> tuple[str, list[str]]:
    # 신규 (Codex→Claude: code/How 제거).
    # 제거 대상: 코드펜스 ```...```, 파일경로 유사 토큰, src/ 참조,
    #            식별자 덩어리(휴리스틱). 제거분은 dropped 로그로 감사(U1 대칭).
```

---

## 7. 라우팅 & 트리거

```python
# route/triggers.py
@dataclass
class TriggerConfig:
    claude_checkin_every: int = 0     # R라운드마다 1회 (0=off)
    claude_on_build_fail: int = 0     # 빌드 실패 연속 N회 시 (0=off)
    dialogue_turns: int = 0           # A안 역채널 상한

def should_call_claude(state: CycleState, cfg: TriggerConfig) -> str | None:
    # 반환: 트리거 사유 문자열 | None. 실행엔진이 이걸로 "체크인" Directive 요청.

# route/router.py
class Router:
    def submit(self, d: Directive) -> None:    # 커널 승인된 Directive 큐잉
    def pending(self, round_no: int) -> Directive | None:  # 실행엔진이 소비
```

호출 비용은 트리거가 통제한다(설계 §4.5): 비싼 Claude는 트리거/사람 요청 시에만,
싼 GPT는 상시. `should_call_claude`가 유일한 자동 Claude 진입점.

---

## 8. 강제 커널 (Friday의 심장)

기존 `integrity.py`의 "assert가 신뢰성의 전부" 철학을 **커널**로 승격한다.

```python
# kernel/authority.py
class Authority:
    """양보 불가한 판단권을 코드로 강제. §6.1 차별점의 코어."""
    def can_issue(self, d: Directive, actor: str) -> bool:
        # halt/redesign/verdict 는 origin 에 human 이 포함될 때만 허용.
        # GPT(exec)는 steer/resume 을 스스로 못 냄 → '멈출지'는 절대 GPT가 못 정함.
    def gate(self, d: Directive, actor: str) -> Directive:
        # 위반 시 AuthorityBreach. 통과 시 서명(승인 표식) 후 반환.

# kernel/integrity.py  (기존 3 assert 흡수 + 확장)
def assert_claude_isolation(workspace): ...        # 기존
def assert_surface_cwd(workspace): ...             # 기존
def assert_codex_prompt_clean(prompt, task, preds): ...   # 기존
def assert_reverse_channel_clean(question: str): ...  # 신규: 질문에 How 누출 없나
def assert_mode_invariant(mode, ctx): ...          # validate=정보비대칭, collaborate=역할비대칭

# kernel/mode.py
class Mode:
    VALIDATE = "validate"      # 정보 비대칭 (기존 friday)
    COLLABORATE = "collaborate"  # 역할 비대칭 (아이언맨/FRIDAY)
    def policy(self) -> dict:  # 어느 assert를 켤지, 대화/역채널 허용 여부
```

**커널 규약:** 대화 엔진·실행 엔진·라우터는 커널 인스턴스를 주입받고, Directive의
발효·경계 교차는 반드시 커널 메서드를 통과한다. 우회 경로가 코드에 없어야 한다
(테스트로 강제, §20).

---

## 9. 표면 (TUI / 대시보드 / HTTP)

### 9.1 TUI (기존 tui.py 분해)

- `convo_view`: 사람⇄Claude 대화(스트리밍 출력, 입력 프롬프트).
- `cycle_view`: GPT 라운드 상태(기존 `_render_cycle`/`monitor`).
- 두 뷰는 `bus.tail`로 이벤트 구독. 입력은 `ConversationEngine.human_says`로.

### 9.2 HTTP 서버 보안 패치 (리뷰 Medium#4 — 필수)

`web/server.py`는 기존 `control_server.py`를 승격하되 반드시:

1. **Origin/CSRF**: POST에 `Origin` 검사 + 부팅 시 생성한 토큰(`flags/ui.token`)을
   헤더로 요구. 토큰 없으면 403.
2. **GET 경로 탐색 차단**: `dashboard/` 밖으로 resolve되는 요청 거부(기존
   `root in target.parents`는 `task/`·`predictions/` 노출 → 화이트리스트로 교체).
3. 바인딩은 `127.0.0.1` 유지.

---

## 10. 설정 스키마 (전체)

```yaml
# config.yaml — friday
mode: validate            # validate(정보비대칭) | collaborate(역할비대칭)

bandwidth_level: 1        # forward 필터: 1(action/where) | 2(expected 허용)
round_budget: 30          # 라운드 상한
call_budget: 0            # 사이클 총 모델호출 상한 (0=무제한 백스톱off)
timeout_seconds: 600

# collaborate 전용
dialogue_turns: 0         # A안 역채널 Codex↔Claude 왕복 상한 (0=off)
claude_checkin_every: 0   # R라운드마다 Claude 체크인 (0=off)
claude_on_build_fail: 0   # 빌드 실패 연속 N회 시 Claude 호출 (0=off)
convo_budget_chars: 40000
convo_recent_turns: 12

context_budget_chars: 60000
context_recent_reports: 6

auth_mode: subscription
intent_providers: [codex, claude]
window: true
```

**무회귀 보장:** 기본값(`mode: validate`, 모든 collaborate 키=0)에서 동작은 현행과
동일. collaborate 기능은 전부 옵트인.

---

## 11. 프로바이더 어댑터

```python
# providers/base.py
class Adapter(Protocol):
    name: str
    def available(self) -> bool: ...          # 설치 여부
    def authenticated(self) -> bool: ...       # 로그인 여부 (기존 _auth_probe)
    def invoke(self, prompt: str, *, stream: bool=False,
               tools: list[str]|None=None, cwd: Path|None=None,
               timeout: int) -> Response: ...

# providers/codex.py — 기존 CLIAgents.codex
# providers/routing_llm.py — 기존 natural.interpret (failover 유지)
#   ※ 리뷰 High#3: claude 페일오버 플래그 실 CLI 검증 후 확정.
```

`Response`: `{stdout, stderr, returncode, approval_requested, timed_out}`.

### 11.1 Claude 권한 프로파일 (역할별로 갈린다)

Claude 어댑터는 **어떤 역할로 부르느냐**에 따라 권한 프로파일을 바꾼다. 하나의
플래그로 통일하지 않는다.

| 프로파일 | 언제 | 호출 형태 | 근거 |
|---|---|---|---|
| `isolated_exec` | validate 모드 **사용자-턴**(surface에서 과제 실행) | `-p ... --allowedTools Bash --disallowedTools Edit,Write,Read,Glob,Grep`, `cwd=surface` | 격리 유지(정보 비대칭). Read 차단이 소스/.pyz 열람 봉쇄. 잔여 U4. |
| `advisor` | collaborate 모드 **대화 파트너**(사람 조언, 샌드박스 과제 아님) | `-p ... --permission-mode bypassPermissions` (스트리밍) | 승인 대기로 멈추면 대화가 끊김. 조언자는 격리 대상이 아님. |
| `routing` | 자연어 의도 분류(failover) | `-p ... --output-format json --json-schema ...` | High#3에서 플래그 실 CLI 검증 필요. |

```python
# providers/claude.py
class ClaudeAdapter:
    def invoke(self, prompt, *, profile: str, cwd=None, stream=False, timeout): ...
    #  profile ∈ {"isolated_exec", "advisor", "routing"}
    #  프로파일 → 플래그 매핑을 한곳에서 관리.
```

**함정(기존 코드 실측 계승):** `bypassPermissions`는 `--dangerously-skip-permissions`
로 매핑되며 **root 실행 시 CLI가 거부**한다. 그래서 `isolated_exec`는 bypass를 쓰지
않고 allowlist로 남긴다. `advisor`에서 bypass를 쓰되, root/거부 환경에서는
어댑터가 `AdapterError`로 명확히 실패하고 표면에 사유를 노출한다(조용한 무동작 금지).
`advisor`는 surface cwd/격리 assert 대상이 **아니다**(과제 수행이 아니므로) —
`kernel.mode.policy()`가 프로파일별로 어떤 assert를 켤지 결정한다.

---

## 12. 시간·난수·결정성

- 스크립트/워크플로 제약과 동일하게 **`Event.ts` 등 타임스탬프는 진입점에서 주입**
  하고 내부 로직은 시계에 의존하지 않는다(테스트 결정성).
- id 생성은 카운터 기반(파일 개수) — 기존 `verdict_{n:03d}` 방식 계승, `Math.random`
  류 비결정 금지.

---

## 13. 동시성 모델

- **프로세스 3종**: (1) TUI/표면, (2) 실행 워커(`friday run --attach`, 기존 `_worker`),
  (3) HTTP 서버(`--serve`).
- 공유는 파일. `events.jsonl` append는 OS append-atomicity + 어드바이저리 락
  (`flags/*.lock`). `status.json`/`context.json`은 tmp+rename(기존 패턴 유지).
- 대화(사람 페이스)와 실행(무인)은 **독립 프로세스**. Directive만 커널→라우터
  파일(`directives/`)로 오간다. 실행 워커는 라운드 시작 시 `directives/`를 스캔.

---

## 14. 영속·재개·크래시 복구

1. 콜드스타트: `events.jsonl` replay로 인메모리 상태 재구성. 없으면 `status.json`.
2. `reports/` 스캔으로 완료 라운드 확정(기존 `_restore_state` 계승 — report 존재
   또는 void까지만 복원).
3. 대화: `convo/session_SSS.jsonl` 재생.
4. 진행 중 크래시: `muto.pid` 부재 + 마지막 이벤트로 판정, `friday run` 재발행 시
   마지막 완료 라운드 다음부터(기존 동작).

---

## 15. 오류 처리 & 예외 계층

```python
# errors.py
class FridayError(Exception): ...
class IntegrityBreach(FridayError, AssertionError): ...   # 기존 유지
class AuthorityBreach(FridayError): ...                    # 신규: 판단권 위반
class AdapterError(FridayError): ...                       # CLI 실패/미설치
class ConfigError(FridayError): ...
```

정책: IntegrityBreach/AuthorityBreach → 해당 라운드/Directive void, 이벤트 기록,
사이클 정책에 따라 정지(기존 "wrong report worse than none" 계승).

---

## 16. 관측성

- `events.jsonl` = 1차 관측면. `friday tail`(신규 서브커맨드)로 실시간 팔로우.
- `friday status`(기존) = 한 줄 요약.
- dropped 로그(forward/reverse 양방향) = 필터 감사(U1 철학).
- 대시보드 = 라운드 곡선/사분면 + (신규) 대화 요약 패널.

---

## 17. 테스트 전략

| 층위 | 대상 | 예 |
|---|---|---|
| 단위 | 필터·커널 assert·트리거·directive 추출 | reverse_filter가 코드펜스 제거 |
| 커널 강제 | **우회 불가** 속성 | exec가 halt Directive를 스스로 못 냄(AuthorityBreach) |
| 통합 | 스크립트 에이전트로 사이클 | 기존 `ScriptedAgents` 확장, 대화+실행 합동 |
| 속성 | 정보/역할 비대칭 불변식 | validate 모드에서 Codex 프롬프트에 task 라인 0 |
| 회귀 | 기본 config = 현행 동작 | 기존 테스트 전부 통과(무회귀) |
| 표면 | HTTP 보안 | 토큰 없는 POST=403, 경로탐색=404 |

**환경 주의(이번 세션 실측):** Windows cp949 로케일에서 인코딩 미지정 `write_text`가
깨진다. 테스트는 파일 IO에 `encoding="utf-8"` 명시, CI는 `PYTHONUTF8=1`.
심링크 테스트는 권한 필요(Windows) → 스킵 마커.

---

## 18. 단계별 마일스톤 (무회귀 우선)

- **M0 — 리팩터(행동 불변).** 기존 코드를 §2.1 레이아웃으로 이동, 어댑터화,
  bus/status 단일화. 기존 테스트 그대로 통과. **코드 증가, 행동 동일.**
- **M1 — 커널.** authority/mode/integrity 승격 + 역채널 assert. validate 정책=현행.
- **M2 — 이벤트 버스.** events.jsonl + tail + 표면 증분 구독.
- **M3 — 대화 엔진(collaborate).** 사람⇄Claude 지속 대화 + Directive 추출.
  `mode: collaborate` 옵트인.
- **M4 — 라우팅/트리거.** checkin/build_fail 트리거로 비용통제 Claude 호출.
- **M5 — A안 역채널.** reverse_filter + Codex↔Claude 왕복(`dialogue_turns`).
- **M6 — 표면 강화.** TUI 대화뷰, 대시보드 대화 패널, HTTP 보안 패치.
- **M7 — 관측성/도구.** `friday tail`, 감사 뷰.

각 M은 이전 M의 테스트를 깨지 않는다(회귀 게이트).

---

## 19. 열린 결정 (구현 착수 전 확정)

1. **mode 양립 vs 피벗**: validate를 영구 유지할지, collaborate로 수렴할지.
2. **판단권 강제 위치**: authority.gate만으로 충분한지, 파일 권한까지 걸지.
3. **reverse_filter 강도**: 코드 누출을 어디까지 근사 제거할지(U1 대칭 리스크).
4. **대화·실행 결합도**: Directive 외 채널을 열지(예: 사람이 실행 상태 실시간 관찰).
5. **정지 판정 주체**: 최종 verdict를 사람만(U3) vs Claude 통찰 일부 위임.

> 이 문서는 M0(무회귀 리팩터)부터 착수 가능하도록 작성됨. M0는 열린 결정과 무관.
