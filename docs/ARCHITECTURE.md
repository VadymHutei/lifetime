# Архітектура Lifetime 2.1.0

Статус: контракт версії 2.1.0. За уточненням користувача основним сховищем став MySQL. Фактичні команди — README, OPERATIONS та MYSQL; перевірки — VALIDATION (2.0.0) і MYSQL_VALIDATION (2.1.0). Версії залежностей — DEPENDENCIES і locks.

## Межі продукту

Flask залишається основою; Jinja рендерить семантичний HTML, CSS забезпечує адаптивність, невеликі модулі vanilla JavaScript додають пошук і зручність. Основний сценарій працює без JavaScript. Дві мови: українська (`uk`, типова) й англійська (`en`). Дизайн узгоджується з passgen і gearlog за фактичними локальними референсами.

Сценарій: дата народження → країна / регіон / світ → явний вибір статистичної групи → результат на тому самому екрані або сторінці результату. Дані форми зберігаються при виправленні помилок і зміні мови. Використовуємо POST для нового персонального розрахунку: дата народження не потрапляє у нові URL. Результат не потрібно зберігати у БД.

Показуємо прожитий час та статистичний орієнтир країни з роком і джерелом. Очікувана тривалість життя при народженні — характеристика населення відповідного періоду, а не персональний прогноз. Не називаємо дату народження плюс цей показник «датою смерті», не обіцяємо кількість років, що залишилася конкретній людині. Якщо візуалізуємо такий горизонт, називаємо його статистичним сценарієм і пояснюємо припущення. Для майбутньої оцінки залишкової тривалості потрібні окремі вікові таблиці смертності; їх немає у базовому наборі v2.0.0.

Вік понад статистичний орієнтир — коректний результат без негативного «залишилося жити». Майбутня дата народження, неправильний формат, невідома країна чи група повертають зрозумілу помилку 400 біля відповідного поля. Невідомий ресурс повертає 404; непідтримуваний метод — 405.

## Backend і залежності

Рекомендована структура:

```text
lifetime/
  __init__.py          # create_app(), конфігурація, реєстрація модулів
  config.py            # типові значення + environment
  routes/              # calculator, countries, metadata
  services/            # чисті розрахунки, локалізація, SEO
  repositories/        # операції з даними і транзакції
  analytics/           # capture, classify, sanitize, persistence
  templates/           # Jinja, спільні компоненти
  static/              # CSS, JS, favicon
  cli.py               # імпорт, міграції, purge, replay, звіти
migrations/
data/                  # перевірений snapshot та provenance
tests/
VERSION
pyproject.toml
```

Розрахунки отримують `today` явно; UTC для журналу і налаштована зона календаря (`Europe/Kyiv`) для користувацького «сьогодні». Дні рахуються календарно, тижні — за фактичною різницею днів, роки — за календарною датою; не використовувати сталий 31-денний місяць. Форматування i18n винести з обчислень. Переклади — версійовані файли, без редактора з ключем у URL.

Application factory не виконує SQL-запити під час імпорту модуля. Наявність схеми й активного snapshot перевіряє startup/readiness; імпорт даних виконується окремою CLI-командою до запуску worker. HTTP не викликає зовнішній API статистики. Один активний dataset читається за версією, тому його можна кешувати без зміни глобального стану під час запиту. Оновлення — контрольована активація перевіреного snapshot з інвалідацією кешу, або перезапуск worker.

Рекомендація: SQLAlchemy Core для компактних repository та Alembic для явних міграцій. ORM не потрібен для кількох таблиць. Це трохи більше залежностей, але полегшує міграцію SQLite → MySQL без нового переписування SQL по всьому застосунку. Прямий `sqlite3` допустимий лише якщо команда свідомо відмовиться від підтримки кількох SQL dialect; тоді залишити версійовані SQL-міграції і тестовану repository межу.

Production: актуальний підтримуваний Python і перевірені сумісні pinned залежності; slim-образ, окремий WSGI-сервер, непривілейований користувач, volume для БД та журналу, конфігурація через environment. Не використовувати Flask development server для production. Для Windows development WSGI-сервер має підтримувати Windows; Linux deployment може мати інший сервер. Secrets, робочі БД, spool та access logs не входять до Git або образу.

## Вибір БД та схема даних

Типово — MySQL 8.4 LTS, InnoDB, utf8mb4, одна application database. Reference і analytics мають окремі таблиці, pools та історії Alembic (`alembic_reference_version` / `alembic_version`). Через URL overrides можна рознести їх по двох БД. Транзакції — READ COMMITTED; connect/pool timeout 3 s, read/write 5 s, InnoDB row lock 1 s, recycle 1800 s. MySQL DOUBLE зберігає точність показників; BIGINT — великі лічильники. Edge merge бере row lock, purge обробляє до 1000 конкретних locked IDs за транзакцію й атомарно додає daily counts. Подальші інструкції — MYSQL.md.

SQLite збережено для explicit `DB_BACKEND=sqlite`: окремі `reference.sqlite3` та `analytics.sqlite3`, WAL, short busy timeout. Файли мають бути на локальному persistent volume, не NFS і не незалежні replicas. Профіль MySQL не переносить ці файли чи їхню аналітику автоматично. [Критерії SQLite](https://www.sqlite.org/whentouse.html), [обмеження WAL](https://www.sqlite.org/wal.html).

MySQL обрано користувачем для наявної інфраструктури. Перемикання задається конфігурацією, а не умовами в маршрутах. Production account, grants та hostname налаштовуються окремо; локальний Compose profile служить розробці та перевірці. Spool лишається локальним і потребує replay для кожного app instance.

Reference schema:

| Таблиця | Поля та правила |
| --- | --- |
| `dataset_versions` | `id`, provider, edition/version, source URL, license URL/text, publication/update time, retrieval time, SHA-256 артефакту, snapshot schema version, observation policy, status (`staged`, `active`, `retired`); рівно один активний snapshot |
| `locations` | стабільний внутрішній id, provider code, ISO alpha-2/alpha-3 nullable, `entity_type` (`country`, `territory`, `area`, `aggregate`), `aggregate_type` nullable (`world`, `geographic_region`, `other_group`), slug, definition; типізація відповідає snapshot та `entity_policy.json` |
| `location_texts` | `location_id`, locale (`uk`, `en`), name, locative; унікальна пара |
| `location_aliases` | старий slug / numeric id, target location; явна таблиця відповідності для міграції |
| `life_expectancy` | dataset id, location id, observation year, sex (`total`, `female`, `male`), indicator code, value in years, source record / metadata; унікальна комбінація snapshot + location + year + sex + indicator |
| `region_memberships` | лише якщо потрібне пояснення складу регіону; dataset id, region id, member id; provider regions можуть перетинатися |

Значення зберігати як decimal з достатньою точністю або numeric із явно описаним округленням на показі. Не обрізати точність при імпорті. Відсутнє значення — відсутній запис / null із причиною, а не 0. Між статями, країнами або роками не підставляти непомітний fallback. «Загалом» брати з окремого provider indicator, не рахувати як середнє чоловічого й жіночого. Регіональні агрегати брати готовими з джерела, не усереднювати країни.

Для початкового snapshot World Bank спільний рік спостереження — 2024; дата оновлення джерела — 2026-07-13. Counts, indicators, перевірки, attribution та правила браку даних визначають `docs/DATA_SOURCES.md` і `data/life_expectancy/manifest.json`. Рік спостереження, дата оновлення джерела та дата завантаження — різні поля. Під час майбутнього імпорту всі групи одного location мають показувати один погоджений рік; якщо відсутні, користувач бачить це явно.

Публічний whitelist v2: 217 країн / територій / окремих статистичних areas, 7 типових географічних регіонів і світ. Повний archive snapshot має 295 entities; інші provider groups не стають country pages автоматично. `CHI` та `XKX` — provider codes, не вигадані ISO-коди. UI групування не є юридичним визначенням суверенітету. Null ISO й типи aggregate зберігаються при імпорті.

Database importer потребує адаптера поточної JSON schema: `entities` → locations; provider observations → life_expectancy; `sex=total/female/male` зберігається без перейменування; `legacy_aliases.json` → alias mapping; manifest hashes → dataset metadata. Це окрема задача реалізації: отриманий upstream fixture ще не є live DB. Інтеграційний тест бере реальний перевірений snapshot, імпортує у temporary SQLite і перевіряє counts, типізацію, відсутні значення, alias decisions, precision та ідемпотентність.

Імпорт ідемпотентний, у транзакції, з перевіркою FK, унікальності та діапазонів; активний snapshot змінюється лише після успішної перевірки. Зберігати попередній snapshot для rollback. Версія статистики незалежна від версії сервісу.

## Статистика всіх запитів

Не можна достовірно визначити «людина», «бот» або «шахрай» за одним User-Agent. Ці назви у звітах означають класифікацію з причиною та впевненістю. Валідація і тип клієнта незалежні: пошуковий crawler може виконати валідний запит, людина може отримати 404.

Один запис у `request_events` для кожного HTTP-запиту; окремі views / звіти `valid_requests`, `bot_requests`, `invalid_requests`, `suspicious_requests`. Вони можуть перетинатися; їх counts не складаються у total без урахування перетину. Для взаємовиключного overview використовувати перехресну матрицю `validity × client_class`.

| Вимір | Значення |
| --- | --- |
| `validity` | `valid` (дозволений ресурс / метод, успішна валідація), `invalid` (помилки route / method / input), `not_applicable` (інфраструктурний запит), `unknown` |
| `client_class` | `likely_human`, `claimed_bot`, `verified_bot`, `unknown`; звичайний browser UA сам по собі дає `unknown` |
| `security_class` | `normal`, `suspicious`, `unknown`; причина: probe path, явний payload pattern, аномалія частоти тощо |
| `outcome` | `success`, `redirect`, `client_error`, `server_error`, `interrupted`; записати реальний HTTP status окремо |

Відомий UA пошукового crawler означає `claimed_bot`. `verified_bot` допускається лише після перевірки за офіційними published IP ranges або forward-confirmed reverse DNS за політикою конкретного provider; перевірка і кеш поза критичним request path. Немає підтвердження — залишаємо claimed/unknown. Класифікація аналітична, автоматичного блокування не додаємо. Ruleset має версію, а reason codes зберігаються для повторного аналізу. 500 на коректній формі — `valid` + `server_error`, а не «шахрай».

Мінімальний `request_events`: unique event id; edge request id nullable; UTC timestamp; ingestion source (`app`, `edge`, `legacy`); HTTP method; bounded sanitized path; matched route template і endpoint nullable; safe query keys / allowed coarse values; status; duration; response bytes nullable; client address / address token; IPv4/IPv6 family; normalized bounded User-Agent; local referer path або зовнішній origin без query; locale; dataset version nullable; app version; validity / client / security labels; reason codes; ruleset version; confidence; metadata flags (`truncated`, `redacted`, `edge_only`). Індекси: timestamp, status, classifications + timestamp, address token + timestamp; за потреби route + timestamp. Dataset version у telemetry — стабільний текстовий ідентифікатор, без міжфайлового FK. Звіти через захищений CLI / export; публічного журналу і неавторизованої адмінпанелі немає.

### Redaction та retention

Не зберігати request / response body, Cookie, Authorization, secrets, дату народження, admin_key, email чи повний Referer. Новий розрахунок POST; legacy GET URL редагується ще до persistence. Query працює за allowlist (наприклад locale, country code, статистична група), невідомі keys можна зберігати bounded і очищеними, їх values видаляються. Зберігається reason code виявленої injection, а не payload. Видаляти control characters, CR/LF та потенційні credentials із path/UA, redaction робити й для path segments, зберігати bounded шлях із прапорцем truncation. Випадкові рядки в URL не логувати без очищення.

Для IP типово HMAC токен із секретом і key id, який дає змогу порівнювати повторні запити без raw IP; одна канонізація для IPv4/IPv6. Raw IP можна ввімкнути конфігурацією для операційного дослідження, тоді потрібна окрема коротка retention і доступ лише адміну. DB-поле raw address підтримує IPv6 (щонайменше 45 символів або binary 16 bytes); legacy `varchar(15)` непридатний.

Рекомендовані configurable defaults: detailed events 90 днів, raw IP 7 днів, daily aggregate 365 днів; `0` retention означає явно вимкнений відповідний режим, а не безстроковість. CLI purge запускається системним scheduler і звітує кількість видалених рядків. Політика поширюється на DB, spool і edge logs. Опублікувати коротку сторінку приватності з реальною політикою. Дата народження не зберігається у статистиці.

### Надійність capture та межа інфраструктури

`before_request` збирає request metadata і результат валідації; зовнішня WSGI-обгортка фіксує status, тривалість та закриття iterable. Один writer entry point зі guard `recorded` / unique event id запобігає дублюванню. Flask error handler не виконує INSERT самостійно. `teardown_request` використовується для cleanup, а не другого журналювання. Обгортка має охоплювати Flask static та відповіді 404/405/500; streaming exception після headers позначає `interrupted`, не вигадує клієнтові новий HTTP status. [Lifecycle Flask](https://flask.palletsprojects.com/en/stable/lifecycle/).

Основний шлях — синхронний короткий INSERT у analytics DB після формування відповіді, з обмеженим timeout. Якщо DB недоступна — append у локальний durable spool із bounded records, permissions, flush і fsync; CLI replay ідемпотентно переносить записи у DB. Multiworker append робити під lock або у файли на worker з атомарним завершенням records; перевірити crash recovery і частково записаний останній record. Для analytics WAL використовувати `synchronous=FULL`, якщо прийнята вимога стійкості до power loss. In-memory queue не є єдиним сховищем. Журналювання працює fail-open: збій DB або spool не змінює вже сформовану HTTP-відповідь, не викликає той самий HTTP handler, не рекурсивно логить власну помилку. Збій пишеться окремо в stderr / операційний лічильник. Якщо всі сховища або диск недоступні, абсолютна безвтратність неможлива: відображати dropped-events metric, сповіщати оператора, не заявляти 100% capture.

Зворотний proxy не має обходити capture для static, robots чи sitemap без окремого ingestion. Базове просте розгортання направляє ці запити через WSGI. Для охоплення відповідей самого reverse proxy (413/502, заборонені шляхи, edge static) потрібні sanitized structured access logs і CLI ingestion у ту саму БД. Edge генерує request id, видаляє supplied request-id клієнта, передає trusted id у app; upsert за цим id об'єднує app annotation з final edge status без подвійного count. Запити, які не дійшли до app, мають `edge_only` і не вигадану app validity. Edge logs проходять ті самі redaction і retention; не залишати стандартний raw `$request` з birth_date query паралельно.

ProxyFix / forwarded headers використовувати лише для відомої кількості trusted proxy hops, коли application port недоступний клієнтам напряму, а edge очищує forwarded headers. IP з довільного `X-Forwarded-For` не вважати достовірним. За відсутності такого контракту remote address — socket peer. HTTPS canonical URL будується з configured `PUBLIC_BASE_URL`, а не з неперевіреного Host. [Контракт довіри ProxyFix](https://werkzeug.palletsprojects.com/en/stable/middleware/proxy_fix/).

Обсяг «всіх запитів»: усі HTTP-запити, прийняті контрольованим edge або application server, включаючи static, HEAD, redirects, errors. DNS/TLS failure до HTTP і мережевий DDoS не є Flask request events; їх може бачити лише окремий інфраструктурний моніторинг. Перелік включень і можливі пропуски перевіряються deployment тестом.

## SEO та URL migration

`PUBLIC_BASE_URL` — один production HTTPS origin, перевірений конфігурацією. Головна й довідкові сторінки мають унікальний title, опис, один основний H1, логічні H2/H3 та корисний локалізований текст. Країни й регіони отримують джерело, рік і статистичні групи; за браку перекладу не індексувати порожній template.

Canonical для indexable сторінок — абсолютний URL без tracking query. `hreflang` — взаємні `uk`, `en`, self-reference і `x-default` на погоджену landing; `html lang` та назви мов — справжні BCP 47 коди. [Локалізовані версії Google Search](https://developers.google.com/search/docs/specialty/international/localized-versions). OpenGraph використовує `property`, без персональних параметрів. JSON-LD генерується словником і Jinja `tojson`, а не інтерполяцією неперевірених рядків: WebSite для сервісу, WebApplication для калькулятора, WebPage/BreadcrumbList для довідника. Dataset доречний на сторінці джерел лише для фактично представленого набору з provenance й attribution. Розмітка відповідає видимому тексту; не обіцяє rich results.

Усі персональні результати та error/admin сторінки мають `noindex` (meta або X-Robots-Tag); results також `Cache-Control: no-store`. Не включати results у sitemap і не будувати canonical з birth_date. Robots disallow сам по собі не виключає сторінку з індексу: crawler має побачити noindex; results не блокувати у robots лише задля приватності. Robots не є access control. [Google noindex](https://developers.google.com/search/docs/crawling-indexing/block-indexing).

`robots.txt` і `sitemap.xml` генеруються з одного route registry і configured origin, відповідають правильним content types. Sitemap містить лише canonical indexable 200 URLs: landing, локалізовані довідники, country/region pages, джерела. `lastmod` — дата реального оновлення змісту чи даних, а не час запиту / кожного deploy. XML escaping і абсолютні HTTPS URL обов'язкові; robots містить адресу sitemap. [Побудова sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).

| Legacy URL | v2 поведінка |
| --- | --- |
| `/` | 302 до `/uk`, без персонального query; canonical landing — `/uk` |
| `/ukr`, `/eng` та їх public country/countries шляхи | 301 до відповідних `/uk`, `/en` і збережених slug; без redirect chain |
| `/ukr/result`, `/eng/result` GET із legacy numeric country / sex | compatibility handler валідує та відображає результат зі зміненою термінологією; noindex, no-store, redaction; не пересилає birth_date у Location |
| старі country aliases / ids | explicit mapping; для 8 `retained_unavailable` — сторінка 200 із поясненням відсутності зіставних даних, noindex, поза sitemap; невідомі поза mapping — 404, без підміни world |
| `/rus` і його сторінки | 410 з поясненням вилучення мови і явними посиланнями на uk/en; без масового redirect усіх сторінок на головну |
| `/translations*` | застарілий редактор вимкнений; 410, noindex, admin_key видаляється з журналів |

Для нових slug alias map допускає 301 лише на відповідний зміст. World lookup за стабільним provider code, не numeric id 181. Нові result URL підтримують POST; query-less GET дає форму чи пояснення зі зрозумілим status. Канонічні slug з legacy зберігати, якщо немає фактичної потреби змінювати.

## Версія і реліз

Одне джерело версії: кореневий `VERSION`, поточний реліз `2.1.0`. Footer, CLI, package metadata і telemetry app_version читають те саме значення; runtime не викликає git. Package / Docker build перевіряє присутність VERSION; файл включений в артефакт. Dataset version не прирівнюється до SemVer застосунку.

На release commit після acceptance створювати annotated git tag `vMAJOR.MINOR.PATCH`; CI перевіряє `tag[1:] == VERSION == package metadata`. Не пересувати старі release tags. Release notes описують зміни та deployment міграцію. Push і production deployment виконувати згідно з окремою авторизацією користувача.

## Legacy ризики і перехід

Підтверджено читанням поточного repository:

- `app/main.py` завантажує всі довідники й переклади з MySQL при імпорті та hardcode world id 181; запуск залежить від доступної старої БД.
- `result()` напряму виконує `strptime` і `int` над query без обробки ValueError; майбутня дата не перевіряється; прихований `sex=1` і country input роблять статистичну групу / географію непомітними.
- `lt_lib.decomposeDate` плутає months/days з `years_raw`, має наближений 31-денний місяць; правила форм для 111–114 не повторюють modulo-100 exception.
- `lt_lib.log` викликається лише у деяких fallback 404, відкриває SQL-з'єднання синхронно і не має fail-open; `log.ip varchar(15)` не підтримує IPv6, `url varchar(64)` обрізає шляхи.
- `/translations*` має ключ у query, видалення через GET та mutable global translations; цей редактор не переносити як є.
- Кореневі `db_setup.sql` / `db_data.sql` мають новішу нормалізовану модель ніж `db/*`; останні містять іншу схему. Перед будь-якою міграцією визначити реальну live schema, зробити backup і протестувати її export. Не виконувати обидва seed scripts.
- `db/db_log.sql` містить історичні IP та запити. Не переносити цей dump як seed нової статистики, не вважати його мітки ботів доказовими; legacy import, якщо потрібен, позначати `legacy`, classifications `unknown`, окремо від v2 counts. Політику зберігання старого dump погодити перед видаленням.
- `app/nginx1.conf` обходить Flask для static; robots/sitemap aliases ведуть у `/app/`, хоча файли лежать у `app/static/`. `create_sitemap.py` hardcode HTTP origin і ставить date.today() усім сторінкам.
- JSON-LD збирається inline strings; OpenGraph має `name` замість `property`; перемикач мов веде на landing і втрачає контекст.

Порядок переходу: snapshot backup → mapping legacy entities → міграції у новій БД → перевірений dataset import → compatibility route tests → staging smoke/load/SEO → rollback rehearsal → release. Не переносити невідомі numeric ids через припущення. Backup SQLite виконувати через backup API або контрольований snapshot з урахуванням WAL; копії лише основного файлу під час запису недостатньо. Rollback: попередній app image, активний dataset і сумісна схема / відновлений backup; перевірити на staging.

## Критерії приймання

1. Основний калькулятор працює без JS українською й англійською; неправильні поля дають 400 зі збереженням даних; майбутня дата відхиляється; 29 лютого й перевищення орієнтира обробляються коректно.
2. Статистика кожної країни / регіону має групу, рік, джерело й dataset version; немає підміни missing нулями, середніми чи іншим роком. Повторний import не створює дублів; невдала перевірка не активує snapshot.
3. БД містить окремі звіти валідних, ботів, невалідних і підозрілих запитів; валідний claimed crawler не перетворюється на invalid, а людська помилка 404 автоматично не стає ботом.
4. Capture тестує public GET, result POST, legacy GET, HEAD, static 200/304/404, redirects, malformed form 400, 404, 405, controlled 500, streaming failure і edge-only 413/502; один request id дає один event.
5. SQLite lock / DB down → durable spool → replay дає збережені записи без дублювання; відмова spool не змінює response і підвищує dropped-events metric. Concurrency тест із реальним worker count підтверджує timeout, latency та retry budget.
6. У БД, spool та edge logs немає birth_date, admin_key, Cookie, Authorization, повного query/Referer чи body. Тести містять IPv6, spoofed forwarding, CR/LF, секрет у path, довгий UA, oversized path, не-ASCII.
7. Перевірено canonical/hreflang reciprocity, валідний JSON-LD/XML, sitemap лише з 200 indexable сторінок, noindex/no-store results, 410 rus і одноетапні public redirects. Host spoof не змінює origin sitemap.
8. Footer / CLI / package / telemetry / annotated tag узгоджені; release build включає VERSION; нова runtime-схема відновлюється з backup.

Тести мають перевіряти поведінку й ризики, а не дублювати private implementation. Мобільний і desktop UI перевіряються браузером, keyboard-only і без JS. План навантаження визначає deployment envelope; його перевищення — підстава перейти на MySQL чи окремий durable collector, а не збільшувати безмежно busy timeout.
