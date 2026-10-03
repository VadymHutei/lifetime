# LifeTime 2.0.0 — ТЗ і план реалізації

Дата: **2026-10-03**. План реалізовано для `2.0.0`; нижче збережено контракт і розподіл робіт. Фактичні перевірки — [VALIDATION](VALIDATION.md), запуск — [OPERATIONS](OPERATIONS.md). Production deployment залишається окремою операцією користувача.

## Вимоги та рішення

| ID | Вимога користувача | Результат для 2.0.0 | Перевірка |
|---|---|---|---|
| R1 | Дизайн у стилі PassGen/GearLog | Спільна темна палітра, панелі, типографіка, зручна форма; HTML/CSS, мінімальний vanilla JS | Браузер: 320/390/768/1280 px, клавіатура, без JS |
| R2 | Переписаний Flask backend, останні версії | Application factory, чисті розрахунки, repositories, конфігурація через environment, pinned stable dependencies | Unit/integration, чисте встановлення, Linux container smoke |
| R3 | Оновлена тривалість життя країн і регіонів | Відтворюваний WDI snapshot, provenance, явний рік і джерело, імпорт у reference DB | Hash/schema/coverage/import/rollback checks |
| R4 | Просування й коректний SEO | Українські/англійські тексти, canonical/hreflang, JSON-LD, robots/sitemap, сумісність старих URL | Route crawl, HTML/JSON-LD/XML, redirects/noindex |
| R5 | Статистика всіх запитів у БД, валідні й боти окремо | Події, незалежні виміри validity/client/security/outcome, окремі звіти, capture app + edge | Статуси, spoofing, redaction, outage/spool/replay/dedup |
| R6 | Версіонування як у референсах | Один `VERSION`, автоматичний футер і softwareVersion, annotated `v2.0.0` | Звірка версій у build/CI, release checklist |
| R7 | Дві мови | `uk` та `en`; російська вилучена за прямою відповіддю користувача | Однакові сценарії, локалізація, legacy `/rus` handling |

Робочі рішення, які дозволяють почати реалізацію без додаткового архітектурного проєктування:

- Українська — типова мова; `/` відповідає 302 до `/uk`. Канонічні локалі `uk`/`en`, legacy `/ukr`/`eng` мають одноетапні redirects.
- Основний продукт — **статистичний орієнтир тривалості життя**, дата народження дає прожитий час і зіставлення з показником населення. Це зберігає основний задум legacy. Питання про альтернативний календар життя було поставлене; за відсутності іншої відповіді він не стає обов'язковим новим продуктом.
- Дані при народженні не є прогнозом залишкових років у поточному віці. Приклад тексту: «Статистичний орієнтир за даними населення, не персональний прогноз». Результат не називає конкретну дату «датою смерті»; вік вище орієнтира має нормальний стан без негативного відліку.
- Форма нового розрахунку — POST, server-rendered HTML; пошук країн і дрібні покращення можуть використовувати JS. Помилки та вибрані параметри зберігаються; основний сценарій працює без JS.
- Початковий deployment-профіль — один Linux host/container, SQLite на локальних volumes: окремо reference і analytics. SQLAlchemy Core + Alembic. Для існуючої зовнішньої MySQL deployment можна адаптувати repository/config після підтвердження інфраструктури; це не потребує зміни доменної логіки.
- Переклади — версійовані файли. Legacy вебредактор із `admin_key` не переноситься. Публічна адмінпанель, акаунти й авторизація користувачів не потрібні для базового сценарію.
- Звіти аналітики — захищені операторські CLI/export, з окремими вибірками валідних, ботів, невалідних і підозрілих подій. Вебдашборд може бути наступним релізом.
- Стиль першого релізу — темний, за фактичними токенами референсів. Світла тема, PWA/offline, акаунти, медичні анкети й персональні прогнози не входять до обов'язкового обсягу.

Деталі: [дизайн](DESIGN_BRIEF.md), [архітектура](ARCHITECTURE.md), [джерела даних](DATA_SOURCES.md), [версії залежностей](DEPENDENCIES.md). Цей план має пріоритет для меж релізу, manifest — для фактичних характеристик snapshot.

## Що підготовлено

- [x] Аналіз legacy та вимог, ризиків і критеріїв приймання.
- [x] Дизайн-бриф за локальними PassGen/GearLog.
- [x] Дослідження офіційних джерел і новий snapshot із raw API responses, hashes та правилами географії.
- [x] Скрипт оновлення і перевірки даних; mapping старих ідентифікаторів/slug із явними невідповідностями.
- [x] Backend, SEO, logging і release-контракти; план розподілу між агентами.
- [x] README, AGENTS, VERSION, CHANGELOG.
- [x] Реалізація backend/UI/міграцій/аналітики/SEO.
- [x] Перевірки нового застосунку, локальний контейнер, release artifact.
- [ ] Production deployment — поза поточним запитом; інструкції підготовлено.

Нові дані підготовлені для імпорту v2. Legacy MySQL або production не оновлювалися; підготовка не змінює робочий сервіс.

## Етапи й залежності

### P0. Зафіксувати контракти — підготовлено

Вхід: це ТЗ, бриф, архітектура, snapshot. Вихід: узгоджені назви маршрутів, форми, типізація geography, schema/import rules, версія й ownership файлів. Перед стартом перевірити `git status` і прочитати AGENTS. Невідповідні legacy географії не зіставляти автоматично за схожою назвою.

### P1. Основа backend і середовища

Власник: backend-агент, `gpt-6.1-sol`, reasoning `high`.

- Створити пакет `lifetime/`, factory, configuration, clock, error handlers, repositories та CLI.
- Підготувати Python/залежності за DEPENDENCIES; lock та чисте встановлення, `.env.example`.
- Розділити reference/analytics connections, визначити timeout/WAL, explicit migrations, readiness; без SQL під час import модуля.
- Завантажувати VERSION з build artifact, передавати у shared template context; prep suffix підтримується.
- Результат: мінімальна програма стартує, health/readiness й помилки мають контракт; тести конфігурації та DB isolation пройдені.

### P2. Reference DB, імпорт і розрахунок

Власник: data/domain-агент, `gpt-6.1-sol`, reasoning `high`. Починається після skeleton і DB interfaces P1.

- Створити schema/міграції для dataset, entities, translations, observations та aliases. Зберігати territory/area/aggregate, provider code і справжній ISO окремо.
- Імпортувати snapshot із перевіркою hashes; ідемпотентність, staged→active activation, збереження попереднього dataset.
- Public scope: країни/території/areas та погоджені географічні регіони/світ із `entity_policy.json`; інші агрегати не змішувати зі списком країн.
- Підготувати українські й англійські назви та відмінки, стабільні slugs; нові geographies потребують перекладів. Upstream англійські назви не видавати за готову українську локалізацію.
- Доменні розрахунки/валідація: календарні дати, 29 лютого, майбутня дата, вік вище орієнтира, missing data, допустимі групи. Clock передається явно.
- Migration mapping: `mapped` імпортувати; 8 `retained_unavailable` зберегти як сторінки 200 із поясненням недоступності зіставних даних, noindex і поза sitemap. Невідомі поза mapping — 404. Не підмінювати England на UK чи старий регіон новим складом. Мовні aliases 301 застосовуються окремо; `expected_http_status` mapping описує кінцеву сторінку geography.
- Результат: імпорт і rollback відтворювані, результати показують групу/рік/джерело, доменні тести проходять.

### P3. HTML/CSS UX/UI та локалізація

Власник: UI-агент, `gpt-6.1-sol`, reasoning `medium`. Може починати паралельно з P2 після узгодження view models.

- Спільні base/header/footer/form/result/error компоненти; CSS tokens із дизайн-брифу, без framework/bundler.
- Екрани: калькулятор, результат із повторним редагуванням, країни/регіони, окрема geography, методика/дані, приватність.
- Visible default «загалом» та зрозумілий вибір geography, жодного прихованого впливового параметра.
- JS лише для progressive enhancement: пошук/filter, збереження контексту. Без-JS шлях обов'язковий, без зберігання DOB у localStorage за замовчуванням.
- Перемикання мови зберігає geography і введену форму через безпечний POST/повторне відображення, не додає DOB до URL.
- Результат: desktop/mobile/browser, keyboard, focus/error states, обидві мови, без JS.

### P4. Журнал усіх запитів і звіти

Власник: analytics-агент, `gpt-6.1-sol`, reasoning `high`. Після P1, паралельно з P2/P3 із окремими файлами.

- Реалізувати event schema, класифікатор із reason/ruleset version, незалежні validity/client/security/outcome, SQL views/CLI summary/export.
- Capture public/static/HEAD/redirect/error, включно 400/404/405/500; один event на запит, worker-safe persistence.
- Redaction до будь-якого дискового запису, bounded path/UA/query, IPv6, trusted proxy, verified vs claimed crawler; без автоматичного блокування.
- Короткий INSERT, durable spool при недоступній БД, ідемпотентний replay, configurable retention і purge. Запис не ламає відповідь користувачу.
- Підготувати edge JSON access log/ingestion і request-id contract для відхилень на proxy та охоплення static, якщо nginx обслуговує їх сам. Врахувати edge/app dedup, запізнілі записи й ротацію.
- Результат: окремі звіти та concurrency/outage/replay/redaction перевірки; точно задокументована межа capture. HTTPS/TCP з'єднання без HTTP request не називати HTTP-подіями.

### P5. SEO, тексти, міграція URL

Власник: content/SEO-агент, `gpt-6-luna`, reasoning `high`; review — `gpt-6.1-sol`, `high`. Після route/view контрактів P2/P3.

- Унікальні title/description, один H1, послідовні H2, природні uk/en тексти, explanatory source/year; без масового keyword stuffing.
- JSON-LD `WebSite`/`WebApplication`, geography `WebPage` + `BreadcrumbList`; `Dataset` лише на сторінці, де реально описано набір. Генерувати JSON серіалізатором, тільки правдиві поля. Structured data не гарантує rich results.
- Canonical і reciprocal `hreflang` uk/en/x-default із configured HTTPS origin; OpenGraph `property`, без Host-header origin injection.
- Robots/sitemap із route registry: тільки canonical indexable 200; actual content/data lastmod, не `today()` при кожному deploy.
- Нові й legacy результати noindex/no-store, без персональних даних у sitemap/metadata. Не закривати noindex-сторінки robots лише для деіндексації.
- `/ukr`/`eng` public aliases → 301; `/rus/**` → 410 із посиланнями на доступні мови; старий translation editor → 410. Legacy result GET обробляти без передачі DOB у redirect.
- Результат: автоматичний crawl, JSON/XML/HTML validation, обидві локалі й негативні URL тести.

### P6. Інтеграція, deployment-пакет і реліз

Власник: координатор `gpt-6.1-sol`, `high`; незалежний reviewer — окремий `gpt-6.1-sol`, `high`.

- Інтегрувати результати P2–P5; оновити README з командами, які вже існують і перевірені.
- Один Dockerfile/Compose профіль, непривілейований runtime, persistent volumes, healthcheck, proxy/capture contract. Точний домен/мережу/volumes звірити з реальною інфраструктурою перед deployment.
- Unit/integration/браузер/SEO, lock audit, container smoke; concurrency на реальній конфігурації workers. Визначити виміряні latency і пропускну здатність, не обіцяти їх без запуску.
- Backup/restore, rollback app+schema+dataset, невдалий імпорт/недоступний logger, відсутність sensitive data у артефактах.
- Після виконання критеріїв: `VERSION=2.0.0`, dated CHANGELOG, release commit, annotated `v2.0.0`. Звірити футер/softwareVersion/package/telemetry/tag. Підготовчі commits не тегувати `v2.0.0`.
- Результат: перевірений release artifact і інструкція запуску. Push/deployment виконуються в межах окремого запиту користувача, підготовча задача їх не запускає.

## Робота сабагентів

Одночасно максимум **координатор + 3 сабагенти**, відповідно до доступного середовища. Використовувати вузькі briefs і мінімальний необхідний контекст. Не запускати більше агентів заради дрібних текстових правок.

| Хвиля | Паралельна робота | Координатор |
|---|---|---|
| Підготовка (виконана) | Data research — Sol/high; architecture — Sol/high; local design references — Luna/high | ТЗ, версії пакетів, README/AGENTS, план і cross-review |
| A | Backend P1; UI прототип P3 на узгоджених fixture models; перевірка локалізованих geography назв | Фіксує routes/form/view/schema contracts |
| B | Data/domain P2; UI P3; analytics P4 | Інтегрує interfaces й перевіряє спільні файли |
| C | SEO/content P5; logging integration; browser QA | Об'єднує changes, запускає acceptance |
| D | Один незалежний reviewer | Виправлення за результатами review, release P6 |

Ownership задавати в кожному brief: `services/repositories/reference migrations`, `templates/static`, `analytics/analytics migrations`, `SEO helpers/texts`. Координатор володіє factory, shared config, dependencies/lock, VERSION, README/AGENTS і release. Для спільних base templates та route registry зміни послідовні через координатора; два агенти не редагують один файл одночасно. Міграції мають узгоджені revision ids/heads.

Sol/high обрано для календарних правил, даних, SQL, безпеки журналу й інтеграції. Sol/medium — для UI за готовим брифом. Luna/high — для обмежених завдань перевірки референсів, локалізації та метаданих із конкретними критеріями. Якщо модель недоступна, використати доступну Sol із таким самим рівнем без блокування роботи. Reviewer отримує код і критерії, а не тільки звіт автора. Повний повторний аудит після кожної дрібної правки не потрібен.

## Gate готовності 2.0.0

Усі R1–R7 мають доказ перевірки. Немає відкритих помилок календарних розрахунків, мовчазних географічних підмін, втрат логів без сигналу, персональних даних у query telemetry, invalid canonical/sitemap або розбіжності версій. Без-JS сценарій працює. Reference import і analytics outage/replay відтворюються на чистій test DB. Production дані не використовуються для руйнівних тестів.

Підготовку завершено; backend/UI реалізовано наступним запитом користувача. Для майбутніх змін зберігається наведений gate готовності. Production публікація не є частиною локальної реалізації.

## Підсумок перевірки підготовки — 2026-10-03

- `python -m unittest discover -s tests -p "test_*.py" -v`: **12 tests, OK**, Python 3.14.3. Включено offline byte-for-byte rebuild у тимчасовій копії, hashes, actual coverage, legacy mapping і regression на невдале оновлення/непідтримуваний рік.
- Незалежний review даних: 225 public geographies без пропусків; усі 188 legacy записів мають mapping або явний unavailable сценарій. Виявлені під час review проблему року поза retained range і неузгодженість version key виправлено.
- Перевірені локальні Markdown-посилання; `git diff --check` без помилок.
- Змінені README і нові prep artifacts. Legacy app, Dockerfile, requirements і SQL seeds не змінені; повний застосунок v2 не запускався, оскільки реалізація є наступним етапом. Release tag не створений.
