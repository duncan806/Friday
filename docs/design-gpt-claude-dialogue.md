# 설계안: GPT(Codex) ↔ Claude 대화 도입

> 상태: **검토용 초안**. 구현 결정 전 트레이드오프 정리 목적.
> 관련 코드: `orchestrator.run_round`, `integrity.py`, `bandwidth_filter.py`,
> `natural.py`, `config.yaml`.

## 0. 배경 — 지금은 "대화"가 금지되어 있다

friday의 존재 이유는 **정보 비대칭을 파일시스템으로 강제**하는 것이다.

- Claude(사용자 역할)는 **Why(task)** 만 보고 코드는 못 본다 → 세계는 `workspace/surface/`.
- Codex(빌더 역할)는 **How(code)** 만 보고 task는 못 본다 → 입력은 `reports/` 뿐.
- 이 박탈은 프롬프트 요청이 아니라 물리적으로 강제된다: `integrity.py`의
  세 assert + `bandwidth_filter`가 신뢰성의 전부.

즉 **"GPT와 Claude가 대화한다"는 요구는 이 전제와 정면으로 부딪힌다.**
핵심 질문은 "호출이 느냐"가 아니라 **"비대칭을 지키면서 대화를 넣을 것인가,
비대칭을 버릴 것인가"** 이다. 호출량은 그 다음 문제(둘 다 상한으로 통제 가능).

## 0.5. 제품 비전 — 아이언맨과 FRIDAY

이 제품의 지향은 **토니 스타크와 그의 AI 비서(JARVIS→FRIDAY)의 협업**이다.
정보를 서로 숨기는 게 아니라 **인지 스타일로 역할을 나눈다**:

| | 배역 | 성격 | 역할 |
|---|---|---|---|
| **Claude** | 토니 스타크(아이언맨) | 느리지만 통찰·판단 | 방향 설정, "이게 맞는가", 멈출 때 결정 |
| **GPT(Codex)** | FRIDAY / JARVIS | 빠르고 구현 잘함 | 실행·빌드 |

이것이 §0의 "정보 비대칭"과 다른 **제3의 축 = 역할 비대칭**이다. 두 축은 배타적:

- **정보 비대칭(기존 friday)**: 서로 상대의 절반을 *못 본다*. 검증(validation)이 목적.
- **역할 비대칭(아이언맨/FRIDAY)**: 서로 *본다*. 대신 느린 통찰(Claude)이 방향을,
  빠른 실행(GPT)이 구현을 맡는 **분업**. 협업이 목적.

**이 비전은 자연스럽게 호출량을 해결한다.** 느리고 비싼 통찰(Claude)은 판단
지점에서만 **드물게** 부르고, 빠르고 싼 실행(GPT)에 **다수 턴을 위임**한다.
즉 "호출이 늘어서 안 되는" 게 아니라, **비싼 쪽을 아껴 부르는 라우팅**이 곧
설계다(§4.5).

### 0.6. 상호작용 모델 — 사람은 Claude와 대화하고, GPT는 일한다

제품의 UX 축은 다음 한 문장이다:

> **사람은 Claude와 "대화"하고(방향·판단·통찰), GPT는 그 뒤에서 계속 "일한다"(구현·빌드).**

```
[사람] ⇄ 대화 ⇄ [Claude: 느린 통찰]      ← 전경, 사람 페이스, 상시 열림
                     │  방향/판단/중단
                     ▼
             [GPT: 빠른 실행] --- 빌드/자가수정 루프 ---   ← 배경, 무인, 상시 가동
```

- **전경(interactive)**: 사람↔Claude의 상시 대화 채널. "무엇을/왜/이게 맞나/멈춰라".
  기존 TUI의 자연어 입력을 **일회성 라우팅이 아니라 지속 대화**로 승격.
- **배경(unattended)**: GPT는 friday의 기존 라운드 루프를 **계속 돌린다**(멈추라는
  판단이 오기 전까지). 사람을 기다리지 않는다.
- **연결**: 사람+Claude의 대화 결론이 GPT 루프에 방향으로 주입되고, GPT의 상태
  (라운드/막힘/빌드결과)가 대화로 요약되어 올라온다.

**이것이 "또 하나의 오케스트레이터"와 갈리는 UX 지점이다** — 사람이 N개 봇을
대시보드로 조율하는 게 아니라, **깊은 파트너 하나(Claude)와 대화 관계**를 맺고
지치지 않는 실행자(GPT)에게 위임한다. 조율 대상이 아니라 **대화 상대**가 제품의 표면.

> 시각화: `docs/`의 대화 흐름 아티팩트(줄별 색상, CRT/Hermès) 참고.

## 1. 현재 호출 회계 (baseline)

`orchestrator.run_round(n)` 기준, 라운드당 모델/CLI 호출:

| 단계 | 호출 | 주체 |
|---|---|---|
| a. 예측(predict) | 1 | `agents.claude` |
| b. 시도(attempt) | 1 | `agents.claude` |
| d. 빌드(build) | 1 | `agents.codex` |
| **합계** | **3 / round** | |

- 사이클: `round_budget`(기본 30) → **≈ 90 호출/사이클**.
- 별도: TUI 자연어 라우팅 `natural.interpret` — 사용자 입력당 1회(라운드 무관).
- 상한 수단은 이미 있음: `timeout_seconds`(기본 600), `round_budget`.

---

## 2. A안 — 경계 유지 + 왕복 채널 (권장)

비대칭은 **그대로 두고**, 리포트 기반의 **제한된 왕복**만 추가한다.
Codex가 리포트를 받고 막히면 "역질문(blockage-question)"을 던지고,
Claude가 답한다. 라운드당 K턴으로 상한.

```
Round N
  Claude --report---> [forward filter] --> Codex
  ┌─ (Codex가 막히면) ────────────────────────────┐
  │  Codex --question--> [reverse filter] --> Claude │  ← 최대 K턴
  │  Claude --answer---> [forward filter] --> Codex  │
  └──────────────────────────────────────────────────┘
  Codex --build
```

### 2.1 새로 필요한 것

1. **역방향 필터(reverse filter)** — 지금은 Claude→Codex 한 방향만 필터한다
   (`bandwidth_filter`가 intent/Why를 제거). 왕복이 생기면 **Codex→Claude 방향도
   필터**해야 한다: Codex의 질문이 코드/경로/심볼(How)을 Claude에게 노출하면
   Claude의 "코드를 못 본다" 불변식이 깨진다. → 코드펜스/파일경로/식별자 스트립.
   **이게 A안의 핵심 신규 엔지니어링이자 최대 리스크.**
2. **채널 파일** — `questions/round_NNN.md`, `answers/round_NNN.md`
   (기존 `reports/`, `dropped/`와 동일하게 파일로 물질화 → 감사 가능).
3. **integrity assert 확장** — `assert_reverse_channel_clean`:
   Codex 질문에 코드/`src` 흔적이 없는지, Claude 답변에 intent가 없는지(기존 필터
   재사용) 사후 검증. 위반 시 왕복 무효(라운드는 유지, 해당 턴만 void).
4. **config 키** — `dialogue_turns: 0` (0=비활성, 기본). 사이클 단위로만 변경.

### 2.2 호출 회계

라운드당 = 1(predict) + 1(attempt) + **2K**(질문+답변 각 K턴) + 1(build) = **3 + 2K**.

| K (dialogue_turns) | 호출/round | 사이클(30R) | baseline 대비 |
|---|---|---|---|
| 0 (현행) | 3 | 90 | ×1.0 |
| 1 | 5 | 150 | ×1.67 |
| 2 | 7 | 210 | ×2.33 |
| 3 | 9 | 270 | ×3.0 |

**선형 증가**. `timeout_seconds`가 그대로 각 호출에 적용되고, K가 하드 상한이라
폭주 불가. 조기 종료(§4)로 실제 평균은 더 낮음.

### 2.3 변경 범위 / 리스크

- 변경: `orchestrator.run_round`에 왕복 루프, `bandwidth_filter`에 역필터 추가,
  `integrity.py`에 assert 1개, 프롬프트 2종(codex 역질문 모드 / claude 답변 모드),
  `config.yaml` 키 1개. 기존 테스트 **불변**(K=0 기본이라 회귀 없음).
- 리스크: **역필터의 정확도**(How 누출 판정)는 `bandwidth_filter`의 intent 판정과
  동일 계열의 근사 문제(README U1의 대칭판). 코드 누출은 정규식으로 100% 못 막음
  → dropped 로그로 감사 가능하게 유지하는 게 현실적 타협.
- **논지 보존**: "모르는 것이 자산" 유지. 대화는 하되 각자 자기 절반만 안다.

---

## 3. B안 — 완전 대화형으로 피벗

정보 비대칭을 **버리고** GPT와 Claude가 필터 없이 공유 트랜스크립트에서
자유롭게 주고받는 협업 에이전트로 재설계.

```
Codex <──────── free dialogue (shared transcript) ────────> Claude
        (no forward/reverse filter, no asymmetry)
```

### 3.1 호출 회계

라운드당 = **2T + 1**(대화 T턴 + 빌드), T는 수렴/상한까지. 상한 없으면 폭주.
반드시 `max_turns` + 전역 호출 상한 필요(§4).

### 3.2 변경 범위 / 리스크

- `integrity.py`의 세 assert, `bandwidth_filter` 전체가 **무력화/삭제** 대상 →
  `test_integrity.py`, `test_filter.py`, `test_orchestrator.py` 대거 재작성.
- 대시보드의 "두 마스코트가 서로 안 만난다"는 불변식(정보 비대칭의 시각화)도 폐기.
- **이건 리팩터가 아니라 다른 제품이다.** friday의 README/spec 전제(§0)와 U1~U4
  공개 문제 전체가 의미를 잃는다.
- 이점: 구현이 오히려 단순(필터·assert 제거), 일반적 멀티에이전트 협업과 동일.

---

## 4. 호출 상한 전략 (A·B 공통)

호출 증가는 다음으로 통제한다 — "늘어나서 안 되는" 게 아니라 **상한을 걸면 된다**:

1. **턴 상한** — A안 `dialogue_turns: K`, B안 `max_turns: T`. 하드 상한.
2. **전역 사이클 호출 상한** — `call_budget` 신설: 사이클 총 호출이 넘으면 중단
   (`round_budget`의 호출 버전). 폭주 백스톱.
3. **조기 종료** — Codex가 "추가 질문 없음" 신호 시 왕복 즉시 종료(평균 호출↓).
4. **호출당 타임아웃** — 기존 `timeout_seconds` 재사용, 지연 폭발 방지.

### 4.5 역할 비대칭 라우팅 (아이언맨/FRIDAY 모델의 핵심)

"호출 증가"를 상한으로 *막는* 대신, **비대칭 라우팅으로 애초에 안 늘게** 한다.
느린 통찰(Claude)은 판단 지점에만, 빠른 실행(GPT)은 반복 실행에.

```
라운드 루프:
  GPT(빠름) 가 T_fast 턴 자율 실행/자가수정   ← 다수, 저비용
  수렴/막힘/의심 시에만:
      Claude(느림) 1회 호출 → 방향·판단·"이게 맞나"   ← 소수, 고비용
  Claude가 "계속" 하면 GPT 루프 재개, "멈춰/재설계" 하면 반영
```

- 호출 분포가 **GPT-heavy / Claude-light** → 총비용은 baseline과 비슷하거나 낮음
  (비싼 호출을 아끼므로). "대화"는 늘지만 **비싼 대화만 아끼면** 예산은 통제됨.
- 트리거(Claude를 언제 부를지)를 규칙으로: 빌드 실패 연속 N회 / GPT가 "판단 필요"
  신호 / R라운드마다 1회 체크인. → `claude_checkin_every`, `claude_on_build_fail`.

## 5. 세 방향 비교와 권장

| | A. 경계유지 왕복 | B. 완전 대화형 | **C. 아이언맨/FRIDAY (역할 비대칭)** |
|---|---|---|---|
| 목적 | 검증 | 일반 협업 | **통찰(Claude)+실행(GPT) 분업** |
| 서로 봄? | 아니오(비대칭) | 예 | 예(정보는 공유, 역할이 다름) |
| 기존 논지 | 유지 | 폐기 | 재정의(정보→역할 비대칭) |
| 호출량 | ×1.67~3 선형 | 폭주 위험 | **≈baseline 이하**(비싼 Claude 아낌) |
| 코드 변경 | 중(역필터 신규) | 대(assert·필터 삭제, 테스트 재작성) | 중(라우팅+체크인 트리거) |
| 마스코트 불변식 | 유지 | 폐기 | 재해석(둘이 만나 협업) |

**대화의 방금 제시된 비전(아이언맨=Claude 통찰, JARVIS/FRIDAY=GPT 실행)에는
C안이 정확히 부합한다.** 권장 경로:

1. **C안을 기본 방향**으로 채택 — "느린 통찰이 방향을, 빠른 실행이 구현을".
   §4.5 라우팅으로 비싼 Claude 호출을 트리거 기반으로 아껴 부른다 → 호출 걱정 해소.
2. 구현은 **플래그 뒤 점진 도입**: `dialogue_turns: 0` 기본 유지 → 회귀 없음.
   GPT 자율 루프 + Claude 체크인(`claude_checkin_every`, `claude_on_build_fail`)부터.
3. 정보 비대칭(기존 friday 검증 모드)은 **버리지 말고 config로 양립** —
   `mode: validate`(기존 A/비대칭) vs `mode: collaborate`(C/역할비대칭).
   같은 코드베이스에서 두 제품 정체성을 스위치.

즉 **B(완전 대화)로 논지를 통째로 버릴 필요 없이, C(역할 비대칭)로 "아이언맨과
FRIDAY"를 구현**하고, 기존 검증 모드는 모드 플래그로 보존하는 것을 권장.

## 6. 미해결/결정 필요 (구현 전)

- **Claude를 언제 부를까**(체크인 트리거 규칙): 매 R라운드 / 빌드 실패 N회 / GPT 신호?
- **공유 컨텍스트 범위**: GPT의 코드/변경을 Claude에게 어디까지 보여줄까
  (전부? 요약? diff만?) — Claude "통찰"의 입력 품질과 토큰비용의 트레이드오프.
- **정지 판정**: 기존 §6 "awaiting verdict"(인간 판단)를 Claude 통찰이 일부 대체할까,
  아니면 최종은 여전히 인간인가(README U3와 연결).
- **모드 양립 vs 피벗**: 검증 모드(비대칭)를 유지할지, C안으로 완전 대체할지.

### 6.1. 차별점 정직 검증 (기록)

"자비스와 토니도 협업한다 — 다른 오케스트레이터도 그렇지 않나?"에 대한 답:
**협업·위계(supervisor) 자체는 흔하다. 차별점이 아니다.** friday가 "또 하나의
오케스트레이터"가 되지 않으려면 다음 셋의 *결합*을 팔아야 한다:

1. **분업 축 = 인지 템포** (능력/툴이 아니라 느린판단 × 빠른실행).
2. **양보 불가한 판단권** (GPT는 무한 능력이라도 "할지 말지·멈출지"는 못 정함).
3. **프롬프트가 아닌 구조적 강제** (역할이 모델이 무시 가능한 제안이 아님).

이 셋을 빼고 "그냥 둘이 대화"만 남기면 남과 똑같아진다 → 구현 시 이 셋 중
최소 하나는 코드로(권한/파일시스템/라우팅 규칙) 강제되어야 한다.

---

### 부록: A안 최소 구현 스케치

```
# config.yaml
dialogue_turns: 1          # 0=비활성(기본) | Codex↔Claude 왕복 상한

# orchestrator.run_round, (c) 필터 직후 ~ (d) 빌드 직전에 삽입
for t in range(dialogue_turns):
    q = agents.codex_ask(reports_text)             # 역질문
    q_clean = reverse_filter(q)                    # How 누출 제거
    assert_reverse_channel_clean(q_clean)          # integrity
    write questions/round_NNN_t{t}.md
    a = agents.claude_answer(task_text, q_clean)   # Why 보유자만 답
    a_kept, a_drop = apply_filter(a, level)        # 기존 intent 필터 재사용
    write answers/round_NNN_t{t}.md (+ dropped)
    reports_text += a_kept
    if codex_signals_done(q): break                # 조기 종료
```
