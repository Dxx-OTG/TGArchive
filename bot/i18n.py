"""All user-facing bot strings, in one place."""


def t(key: str, **kwargs) -> str:
    template = STRINGS[key]
    return template.format(**kwargs) if kwargs else template


def plural(n: int, one: str, many: str) -> str:
    """Pick the singular or plural noun for a count, Title Case by convention (e.g. 1 Member /
    2 Members). Used to build the '{n} {word}' count phrases consistently across the bot."""
    return one if n == 1 else many


STRINGS: dict[str, str] = {
    # /start hub (the primary, command-free menu, navigated in place)
    "hub_home": "🗄 <b>TGArchive</b>\nPick a section, or just paste a @username or t.me link.",
    "hub_browse": "🗂 <b>Browse</b>",
    "hub_data": "📊 <b>Data</b>",
    "hub_check": "✅ <b>Check</b>",
    "hub_help_btn_it": "🇮🇹 Italiano",
    "hub_help_btn_en": "🇬🇧 English",
    "hub_help": (
        "ℹ️ <b>How to use</b>\n"
        "No commands to remember — everything runs from this menu (/start) or from something you "
        "paste.\n\n"

        "<b>📎 Paste to open a card</b>\n"
        "Send — or forward — any of these to open an <b>action card</b>:\n"
        "• a <b>@username</b> (user, bot, group or channel)\n"
        "• a <b>t.me/…</b> link, or a private invite (<code>t.me/+…</code>, <code>joinchat</code>)\n"
        "• a numeric <b>id</b>\n"
        "• or <b>forward</b> a message from a channel\n"
        "The card offers: <b>Scrape · Check · ⭐ Favorite · ➕ Add to archive · Members · Links · "
        "Export · Delete</b>. Every name or link inside a list opens its card the same way; only a "
        "card's own title links back out to Telegram. For a private group you haven't joined the card "
        "still opens (favorite / add / check work) — only Scrape waits until the account joins.\n\n"

        "<b>🤖 Scrape</b> — collect data into the archive\n"
        "Pick what to read, then send the group's <b>@username/link</b>, optionally followed by a "
        "number = how many messages to read (default 500, max 5000):\n"
        "• <b>Members</b> — the member list (groups/supergroups only).\n"
        "• <b>Message senders</b> — who posted, from the last N messages.\n"
        "• <b>Links</b> — the t.me links shared in the last N messages.\n"
        "Re-scraping only <i>adds</i> new data; only links pointing to a real user/bot/group/channel "
        "are kept.\n\n"

        "<b>🔎 Search</b> — look inside the archive (no Telegram call)\n"
        "Choose a category, then type <i>any part</i> of it:\n"
        "• <b>Users / Bots</b> — name, @username, id or link.\n"
        "• <b>Groups / Channels</b> — name, @username or link.\n"
        "• <b>Links</b> — the link or a name.\n\n"

        "<b>🗂 Browse</b> — list everything you have\n"
        "• <b>Groups / Channels</b> — all scraped, with 👥 members and 🔗 links.\n"
        "• <b>Users / Bots</b> — with their 📁 groups and 🔗 shared links.\n"
        "• <b>Links</b> — grouped by where they were shared; 👤 N = how many people shared each (tap "
        "to see who).\n\n"

        "<b>📊 Data</b>\n"
        "• <b>Stats</b> — database totals; tap a number to list them.\n"
        "• <b>Check</b> — reachability (cached ~24h). <i>Check All</i> = every scraped group/channel + "
        "favorites; <i>Check Links</i> = every archived link's target. Each opens options — 🔁 <i>Full "
        "re-check</i> · ⏭ <i>Skip recent</i> · 🧾 <i>Last summary</i> — and can ⏹ <i>Stop</i> (keeps "
        "partial results). Flags: ✅ reachable · ❌ gone/banned · ⚠️ unverified · ▫️ unchecked; dead "
        "ones can be removed.\n"
        "• <b>Export All</b> — the whole archive as a zip.\n"
        "• <b>Delete All</b> — wipe every scraped CSV (favorites kept).\n\n"

        "<b>⭐ Favorites</b> — your saved users/bots/groups/channels. Add from a card (⭐), tap any to "
        "reopen it.\n\n"

        "⏳ <b>Account safety.</b> One Telegram account does every live lookup (resolve/check/scrape). "
        "Check big archives in batches (⏭ <i>Skip recent</i>) and don't spam-paste links, or Telegram "
        "may rate-limit it (FloodWait). Search / Browse / Stats never touch Telegram.\n\n"

        "📖 <b>Full guide:</b> "
        "<a href=\"https://telegra.ph/TGArchive--Guide-EN-07-10\">English</a> · "
        "<a href=\"https://telegra.ph/TGArchive--Guida-IT-07-10\">Italiano</a>"
    ),
    "hub_help_it": (
        "ℹ️ <b>Come si usa</b>\n"
        "Nessun comando da ricordare — tutto parte da questo menu (/start) o da qualcosa che "
        "incolli.\n\n"

        "<b>📎 Incolla per aprire una scheda</b>\n"
        "Invia — o inoltra — una di queste cose per aprire una <b>scheda azione</b>:\n"
        "• uno <b>@username</b> (utente, bot, gruppo o canale)\n"
        "• un link <b>t.me/…</b>, o un invito privato (<code>t.me/+…</code>, <code>joinchat</code>)\n"
        "• un <b>id</b> numerico\n"
        "• oppure <b>inoltra</b> un messaggio da un canale\n"
        "La scheda offre: <b>Scrape · Check · ⭐ Preferiti · ➕ Aggiungi all'archivio · Membri · Link · "
        "Esporta · Elimina</b>. Ogni nome o link in una lista apre la sua scheda allo stesso modo; solo "
        "il titolo della scheda rimanda a Telegram. Per un gruppo privato a cui non sei iscritto la "
        "scheda si apre lo stesso (preferiti / aggiungi / check funzionano) — solo lo Scrape aspetta "
        "che l'account entri.\n\n"

        "<b>🤖 Scrape</b> — raccoglie dati nell'archivio\n"
        "Scegli cosa leggere, poi invia lo <b>@username/link</b> del gruppo, seguito facoltativamente "
        "da un numero = quanti messaggi leggere (default 500, max 5000):\n"
        "• <b>Membri</b> — la lista membri (solo gruppi/supergruppi).\n"
        "• <b>Autori dei messaggi</b> — chi ha scritto, dagli ultimi N messaggi.\n"
        "• <b>Link</b> — i link t.me condivisi negli ultimi N messaggi.\n"
        "Ri-scrapare <i>aggiunge</i> solo dati nuovi; si tengono solo i link che puntano a un vero "
        "utente/bot/gruppo/canale.\n\n"

        "<b>🔎 Search</b> — cerca dentro l'archivio (nessuna chiamata a Telegram)\n"
        "Scegli una categoria, poi digita <i>una parte qualsiasi</i>:\n"
        "• <b>Utenti / Bot</b> — nome, @username, id o link.\n"
        "• <b>Gruppi / Canali</b> — nome, @username o link.\n"
        "• <b>Link</b> — il link o un nome.\n\n"

        "<b>🗂 Browse</b> — elenca tutto quello che hai\n"
        "• <b>Gruppi / Canali</b> — tutti gli scrapati, con 👥 membri e 🔗 link.\n"
        "• <b>Utenti / Bot</b> — con i loro 📁 gruppi e 🔗 link condivisi.\n"
        "• <b>Link</b> — raggruppati per dove sono stati condivisi; 👤 N = quante persone hanno "
        "condiviso ciascuno (tocca per vedere chi).\n\n"

        "<b>📊 Data</b>\n"
        "• <b>Stats</b> — totali del database; tocca un numero per elencarli.\n"
        "• <b>Check</b> — raggiungibilità (in cache ~24h). <i>Check All</i> = ogni gruppo/canale "
        "scrapato + i preferiti; <i>Check Links</i> = la destinazione di ogni link archiviato. Ognuno "
        "apre delle opzioni — 🔁 <i>Ricontrollo completo</i> · ⏭ <i>Salta recenti</i> · 🧾 <i>Ultimo "
        "riepilogo</i> — e può ⏹ <i>Fermarsi</i> (tiene i risultati parziali). Flag: ✅ raggiungibile · "
        "❌ sparito/bannato · ⚠️ non verificato · ▫️ non controllato; i morti si possono rimuovere.\n"
        "• <b>Export All</b> — l'intero archivio in uno zip.\n"
        "• <b>Delete All</b> — cancella tutti i CSV scrapati (i preferiti restano).\n\n"

        "<b>⭐ Favorites</b> — i tuoi utenti/bot/gruppi/canali salvati. Aggiungi da una scheda (⭐), "
        "tocca uno qualsiasi per riaprirlo.\n\n"

        "⏳ <b>Sicurezza dell'account.</b> Un solo account Telegram fa ogni lookup dal vivo "
        "(resolve/check/scrape). Controlla gli archivi grandi a scaglioni (⏭ <i>Salta recenti</i>) e "
        "non incollare link a raffica, o Telegram potrebbe limitarlo (FloodWait). Search / Browse / "
        "Stats non toccano mai Telegram.\n\n"

        "📖 <b>Guida completa:</b> "
        "<a href=\"https://telegra.ph/TGArchive--Guida-IT-07-10\">Italiano</a> · "
        "<a href=\"https://telegra.ph/TGArchive--Guide-EN-07-10\">English</a>"
    ),
    "hub_search": "🔎 <b>Search</b>\nWhat do you want to find?",
    "hub_scrape": "🤖 <b>Scrape</b>\nWhat do you want to scrape?",
    "hub_prompt_su": "🔎 <b>Search Users</b>\nSend a part of name, @username, id or t.me link.",
    "hub_prompt_sb": "🔎 <b>Search Bots</b>\nSend a part of name, @username, id or t.me link.",
    "hub_prompt_sg": "🔎 <b>Search Groups</b>\nSend a part of name, @username or t.me link.",
    "hub_prompt_sc": "🔎 <b>Search Channels</b>\nSend a part of name, @username or t.me link.",
    "hub_prompt_sl": "🔎 <b>Search Links</b>\nSend part of a t.me link or name.",
    "hub_prompt_scm": "🤖 <b>Scrape Members</b>\nSend the group's @username or t.me link.",
    "hub_prompt_scms": "🤖 <b>Scrape Message Senders</b>\nSend the group's @username or t.me link.\nAdd a number after it to read that many messages (default 500, max 5000).",
    "hub_prompt_scl": "🤖 <b>Scrape Links</b>\nSend the group or channel @username or t.me link.\nAdd a number after it to read that many messages (default 500, max 5000).",
    "hub_scrape_done_members": "✅ Scraped <b>{title}</b>\n👥 +{new_added} new members added.\n💾 Saved.",
    "hub_scrape_done_messages": "✅ Scraped <b>{title}</b>\n👥 +{new_added} new senders from {messages_read} messages.\n💾 Saved.",
    "hub_scrape_done_links": "✅ Scraped <b>{title}</b>\n🔗 +{links_saved} new links added ({links_dup} duplicates).\n💾 Saved.",
    "hub_scrape_failed": "❌ Couldn't scrape '{group}' — not found, wrong type, or nothing to collect.",
    "hub_delall_confirm": "⚠️ Wipe the whole archive? Every scraped CSV is deleted (favorites kept). This can't be undone.",
    "home_btn_search": "🔎 Search",
    "home_btn_browse": "🗂 Browse",
    "home_btn_scrape": "🤖 Scrape",
    "home_btn_check": "✅ Check",
    "home_btn_favorites": "⭐ Favorites",
    "home_btn_data": "📊 Data",
    "home_btn_help": "ℹ️ Help",
    "hub_btn_back": "⬅ Back",
    "hub_btn_groups": "🗂 Groups",
    "hub_btn_channels": "📢 Channels",
    "hub_btn_stats": "📊 Stats",
    "hub_btn_export_all": "📤 Export All",
    "hub_btn_delete_all": "🗑 Delete All",
    "hub_btn_check_all": "✅ Check All",
    "hub_btn_check_links": "🔗 Check Links",
    "hub_btn_stop": "⏹ Stop",
    "hub_btn_delete_all_yes": "✅ Delete All",
    "hub_btn_users": "👤 Users",
    "hub_btn_bots": "🤖 Bots",
    "hub_btn_links": "🔗 Links",

    # shared
    "page_prev": "◀ Back",
    "page_next": "Next ▶",
    "page_indicator": "Page {page}/{total}",
    "list_expired": "⌛ Expired — reopen it from the menu.",
    "list_more": "   …and {n} more",

    # Browse groups (groups & supergroups) and channels (broadcast channels)
    "groups_list_header": "🗂 <b>{n} {word}</b>",
    "groups_list_legend": "👥 Users · 🔗 Links",
    "users_list_legend": "📁 Groups · 🔗 Links",
    "groups_list_empty": "No groups yet — scrape one first (🤖 Scrape in the menu).",
    "channels_list_header": "📢 <b>{n} {word}</b>",
    "channels_list_legend": "🔗 Links",
    "channels_list_empty": "No channels yet — scrape a channel first (🤖 Scrape in the menu).",

    # links drill-in (opened from the 🔗 buttons in the group lists and search results)
    "links_group_header": "🔗 {group} — {n} {word}",
    "links_gone": "❌ Those links are no longer available.",

    # members drill-in (opened from the 👥 buttons in the group lists and search results)
    "members_gone": "❌ That group is no longer in the database.",
    "members_header": "👥 {title} — {n} {word}",
    "members_no_username": "(no username)",

    # Search users
    "searchusers_no_result": "❌ Nothing for '{query}'.",
    "searchusers_found_text": "✅ <b>{n} {word}</b> for '{query}' — tap a person to see their groups and links:",
    "searchbots_found_text": "✅ <b>{n} {word}</b> for '{query}' — tap a bot to see its groups and links:",

    # Browse Users / Links (all users, all links)
    "users_list_header": "👤 <b>{n} {word}</b>",
    "users_list_empty": "No users yet — scrape a group's members first (🤖 Scrape in the menu).",
    "bots_list_header": "🤖 <b>{n} {word}</b>",
    "bots_list_empty": "No bots yet — bots turn up while scraping a group's members or message senders (🤖 Scrape in the menu).",
    "links_list_header": "🔗 <b>{n} {word}</b>",
    "links_list_empty": "No links yet — scrape links from a group or channel first (🤖 Scrape in the menu).",
    "link_sharers_header": "👤 <b>Shared by {n} {word}</b>",
    "link_sharers_empty": "No known sharers for this link.",

    # Favorites
    "favorites_empty": "⭐ No favorites yet. Open an entity (paste a @username/link) and tap ⭐ on its card.",
    "favorites_header": "⭐ <b>Favorites</b>",
    "favorites_groups_section": "\n📂 <b>{n} {word}</b>",
    "favorites_channels_section": "\n📢 <b>{n} {word}</b>",
    "favorites_users_section": "\n👤 <b>{n} {word}</b>",
    "favorites_bots_section": "\n🤖 <b>{n} {word}</b>",

    # Search groups / channels / links
    "searchgroups_no_group_found": "❌ Nothing for '{query}'.",
    "searchgroups_found": "✅ <b>{n} {word}</b> for '{query}':",
    "searchlinks_no_result": "❌ Nothing for '{query}'.",
    "searchlinks_found_text": "✅ <b>{n} {word}</b> for '{query}' — tap a link to open it:",

    # Data: stats & export
    "stats_header": "📊 <b>Database</b> — tap a number to see them all",
    "stats_groups": "🗂 Groups: {n}",
    "stats_channels": "📢 Channels: {n}",
    "stats_users": "👤 Users: {n}",
    "stats_with_username": "✅ With Username: {n}",
    "stats_without_username": "❌ Without Username: {n}",
    "stats_bots": "🤖 Bots: {n}",
    "stats_links": "🔗 Links: {n}",
    # stats drill-downs (opened by tapping a count — deep links, see bot/modules/stats.py)
    "stats_all_members_header": "👤 <b>All Users</b> — {n} {word}",
    "stats_all_bots_header": "🤖 <b>All Bots</b> — {n} {word}",
    "stats_with_username_header": "✅ <b>Members With Username</b> — {n} {word}",
    "stats_without_username_header": "❌ <b>Members Without Username</b> — {n} {word}",
    "stats_all_links_header": "🔗 <b>All Links</b> — {n} {word}",
    "stats_no_members": "No members in the database.",
    "stats_no_links": "No links in the database.",
    "export_caption": "📦 {title} — {n} {word}",
    "export_links_caption": "🔗 {title} — {n} {word}",
    "export_all_empty": "Nothing to export — output is empty.",
    "export_all_caption": "📦 Full Archive — {n} {word}",
    "delete_all_done": "🗑 Deleted {n} {word}. Archive emptied (favorites kept).",

    # Scrape (members / message senders / links)
    "scrape_unavailable": "⛔ Scraping unavailable: {reason}",
    "scrape_busy": "⏳ A scrape is already running — try again when it's done.",
    "scrape_started": "🔍 Scraping '{group}'… this can take a while for large groups.",
    "scrape_error": "❌ Scraping error: {error}",
    # Specific, actionable scrape failures (the scrapers raise a typed reason; see collectors/scrape_errors.py).
    "scrape_fail_not_found": "❌ '{group}' not found — check the @username or link (a private group needs a valid invite link).",
    "scrape_fail_not_member": "🔒 '{group}' is private and the scraping account isn't a member yet — join it in Telegram with that account, then scrape. (You can still ✅ Check it and ➕ add it to the archive.)",
    "scrape_fail_wrong_type": "❌ '{group}' is a {kind}, not a group — members and message senders come only from groups/supergroups. For a channel, use 🔗 Scrape Links.",
    "scrape_fail_empty": "❌ Found '{group}', but there was nothing to collect (empty, or nothing new).",
    "scrape_fail_rate_limited": "⏳ Telegram is rate-limiting this account (FloodWait) — try again in about {wait}. Anything already collected is saved.",
    # Generic FloodWait notice, shown wherever a FloodWait blocks a live lookup (card, check).
    "floodwait_notice": "⏳ Telegram is rate-limiting this account (FloodWait) — try again in about {wait}. Nothing was lost.",

    # Check
    "check_busy": "⏳ A scrape or check is already running — try again when it's done.",
    "check_unavailable": "⛔ Check unavailable: {reason}",
    "check_nothing": "Nothing to check yet — scrape a group, channel or add a favorite first.",
    # Check options screen (shown before running, instead of starting immediately)
    "check_options_body": "{total} to check · {fresh} already done in the last 24h.\nRe-check everything, skip the recent ones, or just view the last results:",
    "check_options_body_none": "{total} to check · none done in the last 24h yet.\nRun the check, or view the last results:",
    "check_btn_run": "🔎 Check",
    "check_btn_full": "🔄 Full re-check",
    "check_btn_skip": "⏭ Skip recent ({n})",
    "check_btn_summary": "📋 Last summary",
    "check_started": "🔎 Checking… this can take a while; I'll update as I go.",
    "check_progress": "🔎 Checking… {done}/{total}",
    "check_stopping": "⏹ Stopping — showing the results checked so far.",
    "check_stopped_note": "\n\n⏹ <b>Stopped</b> — showing the results checked so far. Run the check again to finish the rest.",
    "check_aborted_note": "\n\n⚠️ Stopped early: Telegram asked us to wait about {wait} (FloodWait). Partial results saved — run it again later.",
    "check_capped_note": "\n\n⏸ Checked a batch this run — {n} still to go. Run it again (⏭ Skip recent) to continue; spreading it out keeps Telegram from rate-limiting the account.",
    "check_gone": "This list is empty now.",
    # single check
    # follow (add to favorites) after a single check on something not yet archived
    # Check summary
    "check_summary_header": "🔎 <b>Reachability</b>",
    "check_summary_groups": "📂 Groups: {ok} ✅ · {dead} ❌ · {unknown} ⚠️ · {unchecked} ▫️ — {total} total",
    "check_summary_channels": "📢 Channels: {ok} ✅ · {dead} ❌ · {unknown} ⚠️ · {unchecked} ▫️ — {total} total",
    "check_summary_users": "👤 Users: {ok} ✅ · {dead} ❌ · {unknown} ⚠️ · {unchecked} ▫️ — {total} total",
    "check_summary_bots": "🤖 Bots: {ok} ✅ · {dead} ❌ · {unknown} ⚠️ · {unchecked} ▫️ — {total} total",
    "check_summary_lastcheck": "🕓 Checked so far: {n}",
    "check_btn_groups": "📂 Groups ({n})",
    "check_btn_channels": "📢 Channels ({n})",
    "check_btn_users": "👤 Users ({n})",
    "check_btn_bots": "🤖 Bots ({n})",
    "check_btn_lastcheck": "🕓 Last checked ({n})",
    "check_btn_back": "⬅ Summary",
    # drill-down lists
    "check_list_groups_header": "📂 <b>Groups</b> — {n}",
    "check_list_channels_header": "📢 <b>Channels</b> — {n}",
    "check_list_users_header": "👤 <b>Users</b> — {n}",
    "check_list_bots_header": "🤖 <b>Bots</b> — {n}",
    "check_list_lastcheck_header": "🕓 <b>Last checked</b> — {n}",
    # remove inactive
    "check_remove_btn": "🗑 Remove inactive ({n})",
    "check_remove_confirm": "⚠️ Remove {n} inactive {word} from the archive (CSVs) and favorites? This can't be undone.",
    "check_remove_yes_btn": "✅ Remove",
    "check_remove_cancel_btn": "✖️ Cancel",
    "check_remove_none": "Nothing inactive to remove.",
    "check_removed": "🗑 Removed {n} inactive {word}.",

    # Check Links (reachability of every archived link)
    "check_links_header": "🔗 <b>Link reachability</b>",
    "check_links_nothing": "No links in the archive to check.",
    "check_links_remove_confirm": "⚠️ Remove {n} dead {word} from the archive? Their rows are dropped from the link CSVs and the database is pruned. Groups/channels/favorites are untouched.",
    "check_links_remove_yes_btn": "✅ Remove",
    "check_links_removed": "🗑 Removed {n} dead {word}.",

    # entity card (paste a handle/link, or forward a channel post)
    "card_hint": "Send a @username, a t.me link, or forward a message from a channel. Tap ℹ️ Help in /start for a guide.",
    "card_not_found": "❓ Couldn't find or resolve '{q}'.",
    "card_invite_unresolved": "🔒 Couldn't open '{q}' — that <b>invite link</b> looks revoked or expired (or the scraping account is offline). Get a current invite link and paste it again. If the group is already in your archive, it opens on its own.",
    "card_expired": "⌛ This card expired — paste the link again.",
    "card_kind_group": "Group",
    "card_kind_channel": "Channel",
    "card_kind_user": "User",
    "card_kind_bot": "Bot",
    "card_in_archive": "In Your Archive",
    "card_not_archived": "Not Archived Yet",
    "card_group_line": "👥 {members} · 🔗 {links}",
    "card_user_line": "📁 In {groups} Groups · 🔗 {links} Shared",
    "card_check_line": "{glyph} Last Check {age}",
    "card_fav_on": "⭐ In Your Favorites",
    "card_btn_members": "👥 Members",
    "card_btn_links": "🔗 Links",
    "card_btn_usergroups": "🔎 Groups & Links",
    "card_btn_check": "✅ Check",
    "card_btn_fav": "☆ Favorite",
    "card_btn_unfav": "⭐ Unfavorite",
    "card_btn_back": "⬅ Back",
    "card_btn_add": "➕ Add To Archive",
    "card_btn_scrape": "⬇ Scrape",
    "card_btn_rescrape": "🔄 Re-scrape",
    "card_scrape_menu": "What do you want to scrape?",
    "card_btn_scr_members": "👥 Members",
    "card_btn_scr_messages": "💬 Message Senders",
    "card_btn_scr_links": "🔗 Links",
    "card_limit_menu": "How many recent messages to read?",
    "card_btn_export": "📤 Export",
    "card_btn_delete": "🗑 Delete",
    "card_delete_confirm": "🗑 Remove {title} from the archive? This deletes its CSVs (the database updates automatically). Favorites are kept.",
    "card_btn_delete_yes": "✅ Delete",
    "card_deleted_toast": "🗑 Deleted — updating…",
    "card_export_empty": "Nothing saved to export yet.",
    "card_members_header": "👥 <b>Members</b> — {n} {word}",
    "card_links_header": "🔗 <b>Links</b> — {n} {word}",
    "card_user_groups": "📁 In {n} {word}:",
    "card_user_links": "🔗 {n} {word} Shared:",
    "card_check_cant": "Can't check this one — no resolvable handle.",
    "card_fav_toast": "⭐ Saved to favorites.",
    "card_unfav_toast": "Removed from favorites.",
    "card_add_cant": "Only a group or channel can be added to the archive.",
    "card_added_toast": "📌 Added to archive — importing…",

    # middleware
    "rate_limited": "⚠️ Too many requests — slow down.",
    "admin_only": "⛔ Private bot.",
}
