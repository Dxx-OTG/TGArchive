# 🗄️ TGArchive — Telegram Group OSINT Toolkit

> 🇬🇧 English version: [README.md](README.md)

> Bot Telegram + toolkit di scraping per archiviare e cercare membri, mittenti dei messaggi e link condivisi dei gruppi Telegram.
> Pubblicato a scopo di ricerca e didattico: collega uno scraper [Telethon](https://docs.telethon.dev/), un bot [aiogram](https://docs.aiogram.dev/) e [PostgreSQL](https://www.postgresql.org/) in un'unica pipeline `CSV → database`.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-lightgrey)
![License](https://img.shields.io/badge/license-PolyForm--Noncommercial--1.0.0-blue)

---

## ⚠️ Note (leggere prima)

- **Bot privato.** Risponde solo agli ID/username Telegram elencati in `ADMIN_USER_IDS`; ogni altro mittente viene rifiutato in automatico, anche su `/start`.
- **Lo scraping coinvolge dati personali reali** (username, ID utente, in alcuni casi messaggi). La conformità ai [Termini di Servizio di Telegram](https://telegram.org/tos) e alla normativa privacy applicabile (es. il **GDPR** in UE) è responsabilità di chi lo esegue.
- **I segreti restano in locale.** `.env` (token, credenziali) e i file `*.session` (login Telegram autenticato) sono esclusi dal [.gitignore](.gitignore) e non fanno parte del repository. Il template tracciato è [`.env.example`](.env.example).
- `Blacklist.py` nasconde persone/gruppi/canali specifici **ovunque** — ogni lista, ricerca, conteggio (compresi Stats e i conteggi per-gruppo), link e preferito, sia nel bot sia nella CLI, come se non esistessero.

---

## 📑 Indice

**Installa e avvia**
1. [Prerequisiti](#-prerequisiti)
2. [Dipendenze](#-dipendenze)
3. [Installazione](#-installazione)
4. [Configurazione `.env`](#-configurazione-env)
5. [Menu](#-menu)
6. [Trasferire su un altro PC](#-trasferire-su-un-altro-pc)

**Come funziona**

7. [Cosa fa e come si usa](#-cosa-fa-e-come-si-usa)
8. [Struttura del progetto](#-struttura-del-progetto)

**Riferimento**

9. [Raccomandazioni d'uso](#-raccomandazioni-duso)
10. [Limiti di Telegram (FloodWait)](#-limiti-di-telegram-floodwait)
11. [Risoluzione problemi](#-risoluzione-problemi)
12. [Licenza](#-licenza)

---

## 🔧 Prerequisiti

| Requisito | Note |
|---|---|
| **Windows 10 / 11** | Gli script di automazione sono `.bat` + PowerShell. |
| **Python 3.10+** | Deve essere nel `PATH`. Verifica con `python --version`. [Download](https://www.python.org/downloads/) (spunta *"Add Python to PATH"*). `TGArchive.bat` lo verifica in automatico e avvisa se manca o è troppo vecchio. |
| **Git** | Per clonare il repository. [Download](https://git-scm.com/download/win). |
| **winget** | Per installare PostgreSQL in automatico. Già presente su Windows 10/11 aggiornati ("App Installer"). |
| **Un account Telegram** | Per creare il bot e per autenticare lo scraping. |
| **Bot token** | Da [@BotFather](https://t.me/BotFather): `/newbot`. |
| **API ID + API Hash** | Da [my.telegram.org](https://my.telegram.org) → *API development tools* (passo per passo in [Configurazione `.env`](#-configurazione-env)). |

> PostgreSQL viene installato in automatico da **Setup Database** (via winget) — nessuna installazione manuale.

---

## 📦 Dipendenze

Pacchetti Python (in [`requirements.txt`](requirements.txt), installati in automatico in un ambiente virtuale al primo avvio):

```
Telethon>=1.43      # scraping (account utente)
aiogram>=3.13       # bot Telegram
asyncpg>=0.30       # driver PostgreSQL async
python-dotenv>=1.0  # lettura del file .env
watchfiles>=0.21    # rilevazione istantanea delle modifiche ai CSV per il watcher del bot
```

Più **PostgreSQL 17** (installato da **Setup Database**).

---

## 🚀 Installazione

Tutto passa da **`TGArchive.bat`**, il punto d'ingresso unico. Rileva cosa manca e guida passo per passo — creazione di `.env`, compilazione, installazione del database — mostrando il menu completo solo quando tutto è pronto.

### 1. Clona

```bash
git clone https://github.com/Dxx-OTG/TGArchive.git
cd TGArchive
TGArchive.bat
```

### 2. Avvia `TGArchive.bat`

Doppio click su **`TGArchive.bat`** (oppure lancialo dal terminale come sopra) e segui il menu a schermo:

1. Al primo avvio crea `.env` dal template e lo apre in un editor di testo (Notepad, o un fallback se Notepad non è disponibile). Compila `BOT_TOKEN`, `TG_API_ID`, `TG_API_HASH` e `ADMIN_USER_IDS` (vedi [Configurazione `.env`](#-configurazione-env)).
2. Poi propone **Setup Database**: installa PostgreSQL 17, crea il database `scraper`, applica lo schema da `db\migrations\` e scrive le righe `DATABASE_URL_*` in `.env`. Si riapre da solo come amministratore quando serve. Dichiara sempre esplicitamente cosa ha trovato (PostgreSQL non installato / già installato e funzionante / installato ma irraggiungibile) invece di dedurlo in silenzio. Crea sempre e solo uno schema **vuoto** — i tuoi dati scrapati vivono nei CSV in `output\` e vengono (ri)importati nel database al primo avvio del bot o della CLI, quindi un reset non perde mai nulla.
3. Una volta pronto il database, il menu segnala se l'account Telegram di scraping non è ancora autenticato. Scegli **🔑 Telegram Login** per accedere direttamente dal menu (numero di telefono + OTP, più 2FA se attiva) — senza aprire la CLI — così anche lo scraping dall'hub/card del bot funziona. (Anche la CLI ti fa accedere la prima volta che lanci uno scrape.)
4. Con `.env`, il database e il login Telethon tutti pronti, compare il menu completo — scegli **Start The Bot**.

Nessuno script in `scripts\` va lanciato a mano: `TGArchive.bat` li esegue tutti con i controlli giusti. Il menu gira sul Python di sistema (solo libreria standard), quindi non tiene mai `.venv` aperta, e prima di mostrare il menu completo verifica davvero il database (non solo "la porta è aperta"), così distingue "non configurato", "irraggiungibile", "credenziali sbagliate" e "schema mancante/rotto", ognuno con la sua spiegazione.

---

## 🔐 Configurazione `.env`

| Variabile | Valore |
|---|---|
| `BOT_TOKEN` | Token che [@BotFather](https://t.me/BotFather) restituisce dopo `/newbot`. |
| `TG_API_ID` | `api_id` numerico da [my.telegram.org](https://my.telegram.org). |
| `TG_API_HASH` | `api_hash` da [my.telegram.org](https://my.telegram.org). |
| `TG_SESSION_NAME` | Nome del file sessione Telethon. Lasciare com'è (es. `telegram_session`). |
| `ADMIN_USER_IDS` | **Chi può usare il bot.** Username (con o senza `@`) **o** ID numerico, mescolabili e separati da virgola. Es. `@johndoe` o `123456789` o `@johndoe,987654321`. |
| `DATABASE_URL_BOT` | Scritto da **Setup Database** — non modificare a mano. |
| `DATABASE_URL_COLLECTOR` | Scritto da **Setup Database** — non modificare a mano. |

> **Come ottenere `TG_API_ID` e `TG_API_HASH`:** accedi a [my.telegram.org](https://my.telegram.org) col tuo numero di telefono, apri **API development tools** e compila il form *Create new application* — servono solo **App title** e **Short name** (un valore qualsiasi); piattaforma/URL/descrizione non contano. Clicca **Create application**: la pagina si ricarica e mostra **App api_id** (un numero) e **App api_hash** (una lunga stringa esadecimale) — copiali in `.env`. Lo fai una volta sola; gli stessi valori restano validi e ritornando sulla pagina rivedi l'app già creata. Tieni l'`api_hash` privato (è un segreto, come una password).

> Per trovare un ID utente Telegram: lasciare `ADMIN_USER_IDS` vuoto, avviare il bot e inviargli `/start`. La richiesta viene rifiutata, ma la console del bot stampa il `tg_user_id` del mittente. Aggiungerlo a `ADMIN_USER_IDS` e riavviare il bot.

---

## 📋 Menu

**`TGArchive.bat`** è il punto d'ingresso unico. Il suo menu:

- 🤖 **Start The Bot** — avvia il bot in una finestra separata; resta aperta durante l'uso.
- 🛠️ **CLI** — un clone del bot da terminale: gli stessi comandi (ricerca, sfoglia, stats, export, delete, favorites, scrape) sullo stesso database.
- 🔑 **Telegram Login / Cambia Account** — autentica l'account di scraping (telefono + OTP, più 2FA) direttamente dal menu, senza aprire la CLI. Se un account è già autenticato, la stessa opzione propone di **cambiare account**: disconnette il vecchio, elimina il suo file `.session` e autentica il nuovo. L'etichetta riflette lo stato (Login se non autenticato, Cambia Account se già autenticato).
- 🗄️ **Setup Database** — installa o ripara il database (mostrato finché non è pronto).
- 📦 **Prepare Transfer To New PC** — prepara la cartella per un'altra macchina.
- 🧹 **Clean Logs/History** — cancella i file locali in `log\` e, separatamente (ognuno con il suo y/n), le due cache: i risultati del check di raggiungibilità e le identità dei link risolti 24h (schede riaperte). Nessun dato scrapato viene toccato. I token di paginazione/card restano in memoria e si azzerano riavviando il bot.
- ⚙️ **Apri `.env` in un editor di testo** — modifica la configurazione direttamente (Notepad, con fallback automatici se non è disponibile).

---

## 🔄 Trasferire su un altro PC

Per spostare un'installazione funzionante mantenendo l'archivio:

**Sul PC vecchio:**
1. *TGArchive.bat* → **Prepare Transfer To New PC**. Svuota le righe `DATABASE_URL_*` in `.env` e rimuove `.venv`, le cartelle `__pycache__` e i file locali `log\*.log`. I tuoi dati scrapati viaggiano come i CSV in `output\` — nessun dump del DB. (Chiudi prima le finestre del bot/scraping se aperte, così `.venv` non è bloccata.)
2. Copia l'intera cartella sul PC nuovo. Contiene `.env` e `.session`, che sono segreti — spostala su un canale fidato.

**Sul PC nuovo:**
3. Avvia **`TGArchive.bat`**. Ricostruisce `.venv` per questa macchina (un virtualenv non si sposta tra PC), poi esegue Setup Database, che crea un database `scraper` vuoto. Avvia il bot: al primo avvio importa i tuoi CSV di `output\` nel database vuoto, ricostruendo l'intero archivio.

---

## 📖 Cosa fa e come si usa

TGArchive archivia e cerca **membri, mittenti dei messaggi e link condivisi** di gruppi e canali Telegram. Lo usi da un **bot Telegram** senza comandi (il modo principale) o da una **CLI da terminale** equivalente — entrambi lavorano sullo stesso archivio.

### Per iniziare

1. **Accedi una volta** (se non l'hai fatto): dal menu **🔑 Telegram Login** autentica l'account di scraping (telefono + OTP, più 2FA se attiva), salvato nel file `.session` — oppure lancia un qualsiasi scrape da CLI e te lo chiede lì. Il bot stesso non chiede mai il numero di telefono.
2. **Raccogli.** Dal bot: `/start` → 🤖 Scrape, oppure incolla un gruppo/canale e usa la sua card. Dalla CLI: `scrapemembers` / `scrapemessages` / `scrapelinks <gruppo|canale> [limite]`. Il target è un `@username`/link `t.me` pubblico o un invito privato `t.me/+…` a cui l'account si è già unito.
3. **Esplora.** Sfoglia, cerca, salva nei preferiti, controlla ed esporta — dall'hub del bot o dai comandi della CLI. Entrambi leggono lo stesso database, quindi concordano sempre.

### Il bot (senza comandi)

**`/start` è l'unico comando** — tutto il resto avviene nel menu che apre, o incollando un riferimento. Due vie d'accesso:

- **`/start` → menu hub.** Sei sezioni, tutte navigate **in-place** (si edita lo stesso messaggio, niente messaggi nuovi):
  - **🤖 Scrape** — membri, mittenti dei messaggi o link condivisi di un gruppo (scegli quanti messaggi leggere; il re-scrape fonde, mantenendo i dati già raccolti).
  - **🔎 Search** — **users**, **bots**, **groups**, **channels** o **links** (scrivi anche solo una parte di nome, `@username`, id o link t.me).
  - **🗂 Browse** — tutto quello che hai raccolto, per categoria (gruppi, canali, utenti, bot, link), con i conteggi membri/link.
  - **📊 Data** — **Stats**; **Check** (raggiungibilità: Check All + Check Links); **Export All** (zip); **Delete All**.
  - **⭐ Favorites** — le tue entità salvate.
  - **ℹ️ Help** — una guida in-app, in **italiano o inglese** (un tocco cambia la lingua), con un link a questa guida completa.
- **Incolla un `@username` / link `t.me`** (o inoltra un post di canale) → una **scheda azioni** per quell'entità: scrape, check, preferito, vedi membri/link, export, delete, o **aggiungila all'archivio senza scraping**. Anche il link d'invito di un gruppo privato apre la sua card (preferito/check/aggiungi funzionano già prima che l'account entri; solo lo Scrape richiede di esserne membro).

**Tutto è una card.** Toccando un qualsiasi nome o link in una lista (risultati, membri, link di un gruppo, preferiti, stats) si apre la card di quell'entità nello stesso messaggio — solo il titolo di una card linka davvero a Telegram. Le liste sono paginate (◀ / ▶) e ordinate alfabeticamente (utenti senza username in fondo).

### La CLI (clone da terminale)

Un mirror in testo semplice del bot sullo **stesso database e logica** — un terminale non ha bottoni, quindi usa comandi digitati: `searchusers`/`searchbots`/`searchgroups`/`searchchannels`/`searchlinks`, `users`, `bots`, `groups`, `channels`, `members`, `links`, `stats`, `export`, `delete`, `favorites`, `check [all|links|prune]`, `scrape*`, `card`. Incollare un riferimento apre la sua card anche qui.

### Buono a sapersi

- **Lo scraping è additivo** — ri-scrapare un gruppo aggiunge solo nuovi membri/link, non toglie mai ciò che c'è già. Vengono tenuti solo i link a un vero user/channel/group, e una sorgente di link può essere un canale, non solo un gruppo.
- **Aggiungi senza scrape** mette un gruppo/canale/utente/bot in archivio come segnaposto favoritabile e checkabile.
- **I bot** sono distinti dagli utenti in automatico (lo `@username` di un bot finisce in *bot*).
- **Check raggiungibilità** segna le entità ✅ raggiungibile / ❌ sparito-o-bannato / ⚠️ non verificato e può rimuovere i non attivi. È ritmato e in cache 24h per non farsi limitare da Telegram — vedi [FloodWait](#-limiti-di-telegram-floodwait).
- **I tuoi dati sono la cartella `output\`** (file CSV). Il database è solo un indice veloce ricostruito da lì a ogni avvio — usa-e-getta — quindi `output\` è l'archivio vero: **il backup fallo tu**. Bot e CLI non possono girare insieme (condividono un solo account Telegram), quindi chiudine uno prima di aprire l'altro.

---

## 📁 Struttura del progetto

```
.
├── TGArchive.bat          # punto d'ingresso unico (il menu)
├── .env.example           # template di configurazione (copiare in .env)
├── Blacklist.py           # persone/gruppi/canali da nascondere ovunque
├── requirements.txt
├── bot/                   # bot Telegram (aiogram), privato (gate admin-only)
│   ├── main.py            # avvio, middleware, polling
│   ├── card.py, card_view.py     # la "scheda azioni" dell'entità: logica + rendering
│   ├── csv_watcher.py     # importa i CSV nel DB, in tempo reale (watchfiles)
│   ├── telethon_client.py # il client di scraping condiviso, lato bot
│   ├── i18n.py            # tutte le stringhe utente (inclusa la guida in-app EN/IT)
│   ├── middlewares/       # gate admin-only, rate limit
│   └── modules/           # router (hub start, card, check, admin) + helper (search, groups, stats, scrape)
├── CLI/                   # clone del bot da terminale (stesso DB, stessa logica)
│   ├── Menu.py            # REPL: connette DB + Telethon, sincronizza i CSV, smista i comandi
│   ├── commands.py        # handler dei comandi (riusano db.queries; rendering testuale)
│   └── Scrape.py, Messages.py, ExtractLinks.py   # i tre scraper
├── collectors/            # backend condiviso: client Telethon + lock, login, resolve entità,
│                          #   check raggiungibilità, import CSV -> DB, ritmo/throttle
├── db/                    # PostgreSQL: pool, query, blacklist, pulizia
│   └── migrations/        # 0001_init.sql (lo schema completo)
└── scripts/               # .bat + PowerShell: setup DB, transfer, login, pulizia log, menu
    └── _bootstrap_venv.bat # bootstrap venv/dipendenze condiviso, chiamato da ogni script che ne ha bisogno
```

---

## 💡 Raccomandazioni d'uso

- **Proteggi l'account di scraping.** Tutto ciò che è live (risolvere un link, fare check, scrapare) lo fa l'unico account in `telegram.session`. Un uso intenso o a raffica può farlo **limitare/restringere da Telegram** — vedi [FloodWait](#-limiti-di-telegram-floodwait) qui sotto. Se scrapi/checki molto, usa un account **dedicato (di scorta)**, non quello personale.
- **Niente spam.** Evita di incollare decine di link nuovi uno dietro l'altro, e non forzare un re-check completo di un archivio grande in una volta — **procedi a scaglioni** (Check, poi ⏭ Skip recent più tardi). Il bot già si auto-ritma e mette un tetto per run, ma la moderazione ti tiene ben lontano dai limiti.
- **Se Telegram ti limita (un FloodWait):** aspetta il tempo che il bot indica e riprova — è un raffreddamento temporaneo, non si perde nulla. Un account di scorta lo aggira subito (ha un raffreddamento a parte); per rendere il bot ancora più gentile, alza il ritmo in `collectors/throttle.py`.
- **Search/Browse/Stats sono gratis.** Leggono solo il database — zero chiamate a Telegram, quindi usali liberamente anche mentre l'account si raffredda da un FloodWait.
- **Un solo lavoro alla volta.** Bot e CLI condividono account/sessione e un lock impedisce di usarli insieme — chiudine uno prima di usare l'altro.
- **Il re-scrape è additivo** — aggiunge solo nuovi membri/link, non elimina mai ciò che hai già. Ri-scrapa lo stesso gruppo più avanti per aggiornarlo.
- **Nascondi persone/gruppi con `Blacklist.py`** — le voci elencate spariscono da ogni lista, ricerca, conteggio, link e preferito (letto all'avvio: riavvia dopo averlo modificato).
- **`output\` è il tuo archivio — fai il backup tu.** Il database è usa-e-getta (ricostruito da `output\` a ogni avvio), quindi non c'è un backup del DB: i CSV in `output\` (più `.env`/`.session`) sono l'unica cosa non rigenerabile. Copiali ogni tanto in un posto sicuro se i dati contano, e usa **Prepare Transfer** prima di spostarti su un altro PC.

---

## ⏳ Limiti di Telegram (FloodWait)

**Cos'è.** L'unico account in `telegram.session` fa ogni azione live (risolvere un link incollato, fare il check di raggiungibilità, scrapare). Quando fa troppe chiamate troppo in fretta — soprattutto i **resolve** delle entità (`ResolveUsername` / `CheckChatInvite`, che Telegram limita più di tutto) — Telegram risponde "aspetta N secondi": un *FloodWait*. È un raffreddamento temporaneo per singolo account, per farti rallentare — **non è un ban e non si perde nulla.**

**Cosa lo scatena qui.** Soprattutto il **Check** su un archivio grande (ogni target è un resolve, e centinaia di entità mai viste una dietro l'altra sono esattamente il pattern che Telegram frena) e incollare rapidamente tanti link nuovi. Un singolo scrape va bene — sono soprattutto letture ritmate di una chat.

**Cosa vedrai.** Il bot te lo dice, con il tempo di attesa, es. *"⏳ Telegram is rate-limiting this account (FloodWait) — try again in about 1h 15m."* Un check che lo incontra si ferma in anticipo e **salva i risultati parziali**. Aspetta e riprova — vedi [Raccomandazioni d'uso](#-raccomandazioni-duso) qui sopra per come evitarlo.

---

## 🩹 Risoluzione problemi

| Sintomo | Causa / soluzione |
|---|---|
| `BOT_TOKEN missing in .env` | `.env` non creato o non compilato. Vedi [configurazione](#-configurazione-env). |
| Il bot non risponde a `/start` | L'ID/username del mittente non è in `ADMIN_USER_IDS`. La console stampa l'ID del mittente. |
| `Conflict: terminated by other getUpdates request` | Lo stesso bot (stesso `BOT_TOKEN`) è già in esecuzione altrove. Chiudere l'altra istanza. |
| Database rotto / credenziali perse | Lanciare **Setup Database** dal menu. Ripara/azzera il database `scraper` **senza reinstallare PostgreSQL**: riusa le credenziali se `.env` le ha ancora valide, altrimenti recupera l'accesso sul posto. È anche il tipico effetto di lanciare Setup Database da più di una copia di questa cartella - Postgres è un servizio unico condiviso, quindi solo l'ultima copia che l'ha eseguito ha un `.env` valido. |
| Il menu o la console del bot dicono database "raggiungibile, ma le credenziali non funzionano" | Stessa soluzione di sopra (Setup Database). Il menu controlla le credenziali reali prima ancora che provi ad avviare il bot; se salti il menu e lanci `start_bot.bat` direttamente, lo stesso controllo lo fa il bot all'avvio, con lo stesso messaggio. |
| Il menu o la console del bot dicono database "schema mancante o rotto" | Connessione e credenziali sono ok ma mancano le tabelle previste - lancia **Setup Database** per riapplicare lo schema (lo ricrea vuoto; i tuoi CSV di `output\` si re-importano al prossimo avvio, quindi non si perde nulla). Lo stesso controllo esiste sia nel menu che all'avvio del bot. |
| Setup Database dice "trovata un'installazione diversa" e si ferma | Sul PC è già installata una versione di PostgreSQL diversa dalla 17 (nome del servizio Windows diverso) - questo progetto gestisce solo PostgreSQL 17. Disinstalla l'altra versione a mano (Impostazioni > App), poi rilancia Setup Database. |
| `winget not available` durante il setup | Installare "App Installer" dal Microsoft Store, poi rilanciare Setup Database. |
| Modifico `Blacklist.py` / `.env` ma non cambia nulla | Letti solo all'avvio: riavviare il bot (o la CLI). |
| Lo scraping risponde "Scraping unavailable" | La sessione Telethon non è ancora autenticata: lancia **🔑 Telegram Login** dal menu (telefono + OTP) — oppure apri la **CLI** e lancia un qualsiasi comando di scrape una volta — poi riavvia il bot. |
| "another TGArchive process is already connected" | Previsto, non è un bug: la CLI e il bot condividono un solo file `.session` e un lock automatico impedisce loro di girare insieme. Chiudine uno prima di usare l'altro. |
| La CLI dice "DATABASE_URL_BOT is missing" / "schema missing or broken" | La CLI usa lo stesso database del bot. Esegui prima **Setup Database**, poi riapri la CLI. |

---

## 📜 Licenza

[PolyForm Noncommercial 1.0.0](LICENSE). Solo per uso personale, didattico e di ricerca - **non concesso in licenza per uso commerciale o rivendita**. Fornito "così com'è", senza nessuna garanzia; l'uso conforme alle leggi e ai termini di servizio applicabili è responsabilità dell'utente.
