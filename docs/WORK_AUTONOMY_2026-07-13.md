# Work: восстановление автономного цикла — 2026-07-13

## Подтверждённая поверхность

- Репозиторий: `Omnividente/notion-abuz_ai`.
- Default branch: `master`.
- Фактический live workflow в репозитории: `RDSH Local Live Smoke`. Он собирает и запускает код PR на GitHub runner с environment `live-rdsh`, выполняет startup/readiness smoke и локальный запрос к Notion. Это live validation, но не подтверждённый production deployment.
- Отдельный production/deployment workflow в `.github/workflows` на момент расследования не найден. Поэтому smoke нельзя выдавать за доказательство выкладки на внешний сервер.

## Baseline инцидента

- Последний успешно merged project/runtime task перед остановкой: PR #586, `proxy-audit-context-cancellation`, merged `2026-07-13T06:19:14Z`.
- После него в `master` вошли control-plane PR #587 и manifest-only PR #588.
- Следующий project task `proxy-admin-settings-validation` создал PR #589 и Jules session/task `8407847344633654694`, но цикл остановился.
- Первый blocker #589: immutable base-manifest scope разрешал только `internal/proxy/handler.go` и `agent_tasks.json`, а PR добавил `internal/proxy/handler_settings_test.go`.
- Существующая session уже получила одно контекстное quality-fix сообщение. Новая session не создавалась.
- Восстановление: out-of-scope файл удалён в той же ветке; PR evidence синхронизирован; CI и RDSH Local Live Smoke стали зелёными. Повторный quality run сначала прочитал старый PR event body; актуальный metadata snapshot был запущен через существующий `quality-fix` label.
- Фактический progress delta подтверждён: PR #589 merged в `master` `2026-07-13T17:43:23Z`, merge commit `36c3bbc84643d5e880ef15d467b980a014f04380`.

## Точный цикл остановки

1. Jules завершил runtime diff и открыл PR.
2. Quality gate корректно обнаружил нарушение immutable `allowed_paths`.
3. Orchestrator отправил quality context один раз, но session/PR не дали нового commit delta.
4. Open autonomous PR продолжал блокировать dispatch следующей задачи.
5. Monitor и dispatcher использовали разные concurrency groups, а lease жил в repository variable без compare-and-swap.
6. `sendMessage` не подтверждался повторным чтением Jules API; dedupe зависел преимущественно от token-текста в activities.
7. В результате green/no-op monitor cycles не означали реальный progress.

Дополнительный live baseline в `18:05–18:34Z` подтвердил вторую причину:

- Recovery Router run `29273035119` выполнил action, затем упал на сохранении `JULES_RECOVERY_ROUTER_LEDGER`: GitHub вернул `HTTP 422 Value is too large`;
- старый Next Task выбрал manifest-only `automation-recovery-followup-53bd4476`, хотя root task относился к `internal/proxy/reverseproxy.go`;
- session `3291409405775447211` завершила #594 только изменением `agent_tasks.json`, оставив исходную audit-задачу одновременно с `resolution` и `status: blocked`;
- Router был подписан на CI, smoke, automerge, critic, monitor и dispatcher `workflow_run`, а Burst Monitor десять раз повторял наблюдение одного session state.
- После baseline старый контур всё же провёл runtime PR #595 (`proxy-improve-timeout-logging`) в `master` в `18:49Z`. Это полезный project delta и первый post-baseline runtime sample, но он произошёл до cutover, поэтому сам по себе не доказывает отсутствие 422/event storm и не входит в 12-cycle acceptance нового reconciler.
- Следующий runtime PR #596 действительно содержит 504 timeout handling и прошёл RDSH Local Live Smoke, но Jules session `17692837374834195106` стала `FAILED`, CI остановился только на `gofmt`, а legacy router уже merged #597: перевёл исходную задачу в `blocked` и создал новый manifest-only `automation-recovery-followup-43d91504`. Это live split-brain между session, PR, checks и manifest.

## Архитектурное исправление

`autonomy_reconciler.py` становится единственным владельцем reconciliation и планирования для task/session/PR/checks:

- state machine различает task state, Jules session state, PR/check state и progress state;
- durable ledger хранится в отдельной ветке `automation-state-v2` и обновляется через GitHub Contents API с blob-SHA compare-and-swap;
- lease сохраняется в ledger до постановки executor workflow в очередь;
- recovery и dispatch используют один concurrency group `notion-abuz-autonomy-mutation`;
- `jules_next_task.yml` больше не имеет собственного schedule, selector или recovery loop: он исполняет только точный `task_id` с валидным непросроченным `lease_key`;
- executor повторно проверяет durable lease и отсутствие активной Jules session, затем создаёт session и CAS-записью связывает её с task;
- operational intent сохраняется CAS-checkpoint до approve/sendMessage/comment/delete/session-create; потеря финального save не разрешает повтор side effect;
- idempotency key строится из `session_id`, `state_version` и `activity_fingerprint`, но progress fingerprint учитывает только agent activity, PR head и checks — собственный recovery prompt не сбрасывает счётчик;
- после `sendMessage` orchestrator перечитывает activities и подтверждает доставку/изменение состояния;
- red checks запускают message recovery только при новом PR/check fingerprint; неизменный failure не создаёт repeated message на каждом цикле, а stale recovery остаётся отдельным trigger;
- active session не считается progress: delta требует новой activity, commit, PR head, checks или terminal transition;
- после bounded recovery без delta session завершается, а task сохраняет `deferred` ledger-state с retry condition, evidence requirement и next review time; один таймер без нового evidence не делает task eligible;
- failed checks, annotations, changed paths и bounded sanitized activity excerpts включаются в recovery packet;
- check state дедуплицируется по newest workflow/job run; superseded failure на том же SHA не перекрывает свежий success, а recovery packet получает имя реально упавшего Actions step;
- каждый цикл читает все active sessions, но только bounded recent terminal tail, поэтому сотни исторических sessions не превращаются в сотни Jules API activity calls;
- PR без активной session reconciler чинит через один deduplicated PR comment, не создавая дублирующий PR/session;
- failed open project PR без active session получает bounded in-place recovery lease: executor проверяет номер и expected head SHA, стартует с существующей PR branch и запрещает новый PR; `blocked`/`deferred` manifest state не завершает такую recovery session;
- eligible работа без action/progress завершает workflow ошибкой, а не ложным success;
- selector предпочитает runtime/evidence tasks; control-plane task без конкретного failed run/check evidence не eligible;
- scheduler запрещает две разные control-plane задачи подряд; после blocker repair следующий dispatch должен вернуться к project work;
- controlled scope expansion записывается trusted reconciler в ledger с exact paths, risk, evidence и fingerprint исходной задачи; PR quality job только читает этот snapshot и не позволяет PR самостоятельно расширить scope;
- пустая project queue запускает только read-only/shadow evidence report и завершает цикл actionable error — manifest-only automation meta-task не создаётся;
- `JULES_RECOVERY_ROUTER_LEDGER` читается один раз для bounded migration; дальнейшие записи идут только в `automation-state-v2/autonomy/ledger.json`;
- legacy actions/sessions и v2 messages/tasks/sessions/cycles имеют retention и hard caps;
- старые Recovery Router и Burst Monitor оставлены только как manual read-only compatibility entries: без schedule, `workflow_run`, Jules credentials или write permissions;
- PR job выполняет только read-only unit validation; operational reconcile разрешён только для `refs/heads/master`.

## Проверки

В PR выполняются:

- `python3 -m py_compile` для state, reconciler, leased executor и тестов;
- `python3 -m unittest -v .github/scripts/autonomy_reconciler_test.py`.

Покрыты state versioning, message idempotency, user-prompt-vs-agent-progress, sanitized packet, newest-check dedupe и failed-step context, bounded session inspection, evidence-bound deferred retry, bounded migration/pruning, control-plane blocker evidence, запрет двух control dispatch подряд, trusted scope expansion, stale-scope rejection, runtime priority, exact-task execution, lease mismatch и lease expiry. Legacy workflow tests проверяют отсутствие event storm и один mutation domain.

## Live acceptance

Merge запускает первый reconciler cycle через `push`, затем schedule идёт каждые пять минут. Архитектурный PR не считается полностью доказанным до наблюдения минимум 12 последовательных unattended scheduled cycles. Каждый цикл должен оставить bounded durable ledger evidence и не может быть успешным no-op при наличии actionable work. Отдельно требуются два runtime task → Jules → code/test diff → PR → checks → merge цикла; RDSH Local Live Smoke остаётся PR-code evidence, а не production deployment evidence.
