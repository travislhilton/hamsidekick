# HAM Sidekick Station — ham net speech-to-text

Live speech-to-text for **amateur radio voice nets**, and **keyboard chat and file exchange over the radio** (VARA HF / VARA FM), on a Windows PC connected to one or more radios.

> **An independent volunteer project** (MIT License), offered freely to any amateur radio club, ARES (Amateur Radio Emergency Service) group or EOC (Emergency Operations Center) that can use it. A companion to the [Church of Jesus Christ EMCOMM forms](https://github.com/travislhilton/church-emcomm-wnlk-forms): the station writes the net's ICS (Incident Command System) 309 and 213 messages for Winlink, and can read an EOC's situation report out on a voice net. Machine transcription: the operator reviews everything before it is sent.

HAM Sidekick Station listens to your radio and writes down every transmission a few seconds after the station unkeys. It shows who is talking, looks up every callsign in the FCC (Federal Communications Commission) database, explains Q-codes and prowords, coaches a newer operator through check-ins, relays and emergency traffic, and keeps each net's log, minutes and history. After the net it builds the **ICS-309** communications log and **ICS-213** summary for Winlink Express. It works with **no internet** once installed; a bigger home computer, when there is one, can re-read the net more accurately.

On a **data radio** the station is also a **VARA chat and file station**: through the VARA HF or VARA FM modem you already use for Winlink, it announces your call on a channel, lists the stations it hears, and lets you **chat by keyboard** and **send files** to any of them, radio to radio, with no internet, no Winlink server and no gateway in between. Each message shows when it was delivered; each file shows its progress, speed and time left on both ends, and can be cancelled from either end. **Test link speed** measures what a link to a station really carries and tells you how long a file of a given size will take; VARA FM **digipeaters** reach stations you cannot hear directly. See [Chat and files over the radio (VARA)](#chat-and-files-over-the-radio-vara).

> **Renamed 2026-11:** this project was called *HamNet Station* (repository `ham-net-speech-to-text`). It is now **HAM Sidekick Station**
> (`travislhilton/hamsidekick`; the old address redirects). Run the installer again on an existing PC: it moves the scheduled tasks,
> firewall rule and desktop shortcut to the new names and keeps your folder (`C:\ham-net-speech-to-text`), settings, logs and
> recordings. A new PC installs to `C:\HAM-Sidekick-Station`. The optional AI assistant's default on-air name is
> *Einstein* (it was *Sidekick* until 2026-11-21; the operator can choose another).

## Find your role

| You are | Start here |
|---|---|
| Setting up a station PC for the first time | [Install](#install) — then [After installing — what to do](#after-installing--what-to-do) |
| An operator or net control logging a net | [Running a net](#running-a-net) and the [Quick Reference Card](#quick-reference-card) |
| Sending the net's log to an EOC or your ARES group | [After the net: Winlink messages](#after-the-net-winlink-messages) |
| Chatting or exchanging files with another station over the radio (VARA) | [Chat and files over the radio (VARA)](#chat-and-files-over-the-radio-vara) and the [VARA card](#quick-reference-card) |
| Reading an EOC's situation report out on a voice net | [Incident read-out](#incident-read-out-situation-report-on-a-voice-net) |
| Connecting a radio (handheld, mobile, HF rig) | [Connecting a radio](#connecting-a-radio) |
| An instructor giving a class | [Quick Reference Card](#quick-reference-card) — print one per student |
| Something looks wrong | [When something looks wrong](#when-something-looks-wrong) |
| Every feature in detail | [The manual](docs/MANUAL.md) |
| A developer | [Contributing](#contributing--developing-this-project) and [How it works inside](docs/TECHNICAL.md) |

## Which computer can I use?

| What you are doing | What you need |
|---|---|
| **Running the station** (it records and transcribes the radio) | **A Windows 10 or 11 PC**, 64-bit, about 8 GB free; a laptop works |
| Watching the log, fixing a line, reading the minutes | Any phone, tablet or computer with a browser, on the same Wi-Fi or Tailscale |
| Sending the net's messages by Winlink | The station PC with Winlink Express, or any Windows PC with Winlink Express and the small **Winlink helper** |

**Why Windows:** the station runs beside Winlink Express and VARA (the radio modem Winlink uses), which run only on Windows. Any other device joins by browser.

## Download

| | Best for | Link |
|---|---|---|
| **ZIP package** (the installer is inside: `install\windows\install.cmd`) | Every station PC — the first install and every update | **[Download the ZIP](https://github.com/travislhilton/hamsidekick/archive/refs/heads/master.zip)** |
| **Quick Reference Card** (two sides, US Letter) | Keeping by the radio; handing out at a class | **[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Station_Quick_Reference_Card.pdf)** |
| **Business card** (two sides, Avery 5371, 10 per sheet) | Handing out: HAM Sidekick Station on one side, [Church of Jesus Christ EMCOMM](https://github.com/travislhilton/church-emcomm-wnlk-forms) on the other, each with a QR code to its page | **[Open the card page](https://travislhilton.github.io/church-emcomm-wnlk-forms/training/handouts/business-card-avery-5371.html)** (print, alignment test, nudge) · [PDF](https://travislhilton.github.io/church-emcomm-wnlk-forms/training/handouts/pdf/Business_Cards_Avery_5371.pdf) |
| Einstein: **up to 3 questions** worked on at once, answered in the order asked; outside a net a ready answer is **given at a pause** (3.5 s quiet, a turn-over, or when asked: "This is W9XYZ Einstein, for K7ABC: …"), with the disclosure when it is the first transmission; in a net it still announces and waits for net control. "What did you find?" / "give us your answer" ask for it | built 2026-11-12 |
| Einstein **Chat & prepared…** (`station/chat.py`, `station/topics.py`; a dialog from each radio's Einstein card): a private **chat** with Grok, never transmitted, told this radio's frequency, band and your privileges, the net on now (net control, check-ins with names and towns, traffic, regulars not heard), the last transmissions, the last session's minutes, the **Library** and computed terrain paths between your **Sites** (name | lat, lon | height | note; kept on the PC only); words for the air it writes are Part 97 checked and can be **saved to Prepared**. **Prepared**: saved words and **talks** (a training topic written by the thinking model from the Library, split into one-transmission parts that end handing back to net control with the ID); every item has **▶ Hear** (this PC only, never the radio), edit, **Approve** (bound to the words: an edit un-approves), **Send now** (Send mode only) and **Arm**: then *"Einstein, present the topic"* / *"continue"* on the net says the approved words exactly, no model in the loop | built 2026-11-12, browser-tested on the demo station (`tests/test_topics_chat.py`) |
| Einstein **Send** (a third position on a radio's Einstein switch, offered only when that radio's Transmit switch is on; off by default): a draft that would speak is said on the air after a **3 s countdown** ("Sending in 3… Stop (Esc)"), only while the control operator is **at the station** (keyboard or mouse on the dashboard in the last 3 min), with listen-before-talk (carrier or voice, or anything new heard, cancels it), the frequency known, PTT through the radio's transmitter watchdog. **Esc, Stop or any click drops PTT at once.** The chosen Grok voice, else this PC's Windows voice offline. The ID clock, disclosure, check-in and prepared answers move on only when really sent. Logged to `data/agent_sends.jsonl` (`station/sender.py`, `tests/test_send.py`) | built 2026-11-12, not yet keyed on a real radio |
| **Transmit test…** (Radios… → a radio with Transmit on: tick *a dummy load is connected*, then **Tone + ID** (5 s 1 kHz tone, then your call by voice) or **Phrase + ID**): same 3 s countdown, presence, listen-before-talk and Esc as Send, never moves Einstein's ID clock; sets **Drive level** (0.02-1.0, the deviation), **Lead** and **Tail**, which Send then uses too (`station/sender.py`, `tests/test_send.py`) | built 2026-11-13, not yet keyed on a real radio |
| **Operator walkthrough** (`tools/operator_walkthrough.py`, `tools/operator_install_check.ps1`, `tests/operator/`, `.github/workflows/operator-walkthrough.yml`): follows the Quick Reference Cards step by step as a human operator would. A GitHub Actions job installs on a clean Windows machine the way the card says (download, Unblock, extract, `install.cmd`, callsign, QRZ skipped) and then drives the dashboard in a browser against a throwaway station (add a radio, set level, add a net, the log, End net, Winlink messages…, set up Einstein, open the Band plan, reserve and release an ad hoc VARA channel); all six cards, VARA, band plan and ad hoc included since 2026-11-20; `--mode live --url …` does the read-only half on a real station. Every card item ends PASS, FAIL, SKIP, UNIT (covered by named unit tests) or HUMAN (needs a person, a radio, an account); `tests/test_card_in_sync.py` fails when a card changes without the walkthrough being looked at again | built 2026-11-13, runs on every push that touches the program |
| **Share settings** (Settings → *Share settings with another station*; `station/portable.py`): **Export settings…** writes one file with this station's net schedule (each net's radio as a hint: name, band, mode), Einstein's choices (license class, models, voice, speed; with *include my Einstein identity* also its on-air name, your check-in line, first name and region) and the local names. **Preview import…** on another station shows what would be added or updated, lets you pick which of its radios each of the other station's radios becomes, then **Import these settings**. Never in the file: keys, call sign, radios, sound inputs, history. Importing never deletes (same name and start time = updated), and the files it replaces are saved in `data\settings_backups\` first | built 2026-11-13, tested between two stations in a browser (`tests/test_portable.py`) |
| **Search the nets, and a List view** (Nets → Schedule): a search box above the nets (every word must match: name, frequency such as `146.94`, mode, radio or `no radio`, day, net control; the box keeps its place while the schedule updates) and **Cards / List**: the list shows each net's name, time, frequency and radio, sorts by any column, opens a net from its name, and is remembered on that PC | built 2026-11-13, walked in a browser (desktop + phone width) |
| **Filter, change and delete from the List** (Nets → Schedule): **All bands / HF / VHF / UHF** and **Emergency** filters (with the search, in both views); a second click on a column heading reverses the sort; the **Radio** cell opens the same radio picker as the cards (each radio says whether it can hear the net); tick nets (or the heading box for every net shown) and **Delete**: asked once on the page, the schedule is copied to `data/settings_backups/<time>/` first, history and minutes are kept | built 2026-11-13, walked in a browser (desktop + phone width) |
| **Find nets near you** (Nets → Schedule, needs the xAI key): one xAI web search that works like a local ham: the area's clubs, ARES, RACES / emergency-management and Skywarn groups, repeater associations and the ARRL section's traffic nets, then each one's net schedule; repeater directories too. **Where:** the grid square in Settings, else this PC's location (the browser asks), else an address you type; only a rounded position (about 10 km) is sent, never a street address. **Bands follow your radios:** VHF/UHF only, HF only, or both; Winlink-only radios don't count; digital-voice nets (DMR, D-STAR, Fusion) are left out. **Distance:** VHF/UHF within 50 km by default, HF 800 km, both settable. **HF reach:** from your antenna kind and power, the band, distance and the net's hour, each HF net gets *Hear* and *Check in*: likely / maybe / unlikely (a rough estimate for typical conditions). Each net shows its source (and whether the search opened it), gets a suggested radio, and times given in UTC or another zone are shown in yours. Only nets not already on your schedule are listed (the ones that are, by frequency and time or by name, are named under "found already on your schedule"). Tick nets (or all) → **Add to the schedule**; the net keeps a link to its source and leaves the list. Results are kept a week; one search costs about $0.10–0.30 and takes up to a minute | built 2026-11-13, walked in a browser; one real search checked |
| **Winlink helper** (2026-11-15): the Winlink window puts its messages in the Outbox of **another Windows PC** with Winlink Express: a small helper there (`station/winlink_helper.py`, standard library only; installer `install/windows/install-winlink-helper.ps1`, served by the station as `install-winlink-helper.cmd` with its address inside) asks the station every 3 s for messages (`station/winlink_helpers.py`), builds them from its own Express templates and writes them with the same code and the same rule (Express closed; Data files backed up). The window lists each helper with its state (ready / Winlink Express open / not answering), the one on the browser's own computer first, and follows the job to "written" or the reason it was not | built 2026-11-15 (`tests/test_winlink_helper.py`, the window in a browser); **not yet installed on a real second PC** |
| **VARA call with an SSID** (2026-11-17): each VARA modem has its own call, typed whole as in Winlink Express (W9XYZ-7 here, W9XYZ-8 at another station), kept apart from the Winlink account and the station's callsign; two SSIDs of one callsign are two stations (an incoming link from W9XYZ-7 to W9XYZ-8 was once taken as our own call) | done (`tests/test_varalink.py`, `tests/test_vara.py`) |
| **VARA channel on the radio card + "keyed / heard" check** (2026-11-18): the data radio's card lists who is on the VARA channel (click to chat) and the call in use; after an announcement the window says whether VARA keyed the transmitter and when it last heard a signal; two copies of VARA sharing one RA-Board (PTT) device with different sound cards are named ("VARA FM 2 keys the radio of VARA FM": a copied VARA folder keeps the first copy's PTT device) | done (`tests/test_varalink.py`, `tests/test_varachan.py`) |
| **UX pass 1** (2026-11-18): a data radio's column is its **VARA workspace** (stations on the channel, chat and files under the radio; the pop-up keeps only Modem setup and the by-hand link; the nets strip, Coach / Net board and voice log are not shown on a data radio); the header is grouped (Search · Nets · Band plan · Read-out ‖ Radios… · Settings ‖ view tools · Help) and folds behind **☰ Menu** on a phone; the radio card is slimmer so the log has more room | done (browser-checked at 1920, 1440 and phone width; `tests/test_dashboard_ux.py`) |
| **UX pass 2** (2026-11-18): **Settings sections fold**: a tab with several sections is a short list of rows (the first open, the rest closed, each with a line saying what is inside; what you open stays open in that browser; a link to a setting opens its section), so no tab scrolls. **Every reference card** has two QR codes: "New here? Get the station" (this page) on the front and "Share this card" (its own PDF) on the back. Settings paths in the cards and manual name the tab ("Settings → Einstein & AI → Station agent") | done (`tests/test_phone.py`, `tests/test_station.py`, the operator walkthrough: 37 browser steps pass) |
| **Reference cards: binding margin** (2026-11-18): every card prints with ¾ inch on the binding edge for spiral binding on US Letter: the left of the front and, double-sided, the right of the back | done (`tests/test_phone.py`) |
| **The assistant is Einstein** (2026-11-21): the AI assistant's default on-air name is **Einstein** (was Sidekick); the dashboard, the Settings tab (**Einstein & AI**), the cards and the docs say so. A saved default that was never changed ("Sidekick" or the older "Echo") becomes Einstein once; a name the operator chose stays. The product is still HAM Sidekick Station | done (`tests/test_agent.py`) |
| **Radios…: audio outputs are read fresh** (2026-11-18): an interface moved to another USB port, re-plugged or renamed after the station started now shows under Transmit → audio out (the inputs already did) | done (`tests/test_station.py`, `tests/test_radios.py`) |
| **⚙ Settings… on every radio card** (2026-11-18): opens that radio's settings directly; Radios… lists the radios one line each (name, sound input, frequency, transmit, state), click to open | done (`tests/test_station.py`, operator walk) |
| **VARA: Test link speed** (2026-11-18): on demand, sends random test data to one station for 30 to 120 s and measures the real throughput as VARA steps up; shows the average, the speed reached, VARA's level and S/N, and how long a file of 1 KB to 1 MB would take; the estimate is shown before a file is sent (`docs/VARA.md`: TEST / TESTEND / TESTED, `+TEST` in the handshake) | built; first on-air runs 2026-11-18 (`tests/test_vara.py`, `tests/test_varachan.py`) |
| **VARA: a file on its way shows its progress** (2026-11-18): percent, bytes of the size, transfer rate, time left and time so far, for sending and receiving, with **Cancel** (drops the link; nothing partial is kept); shown at the top of the panel on both stations whatever station is chosen, with how long the frequency stays in use; a short notice goes ahead of the file so the receiver sees it within seconds | built (`tests/test_vara.py`, `tests/test_varachan.py`) |
| **VARA: Open / Show in folder for a received file** (2026-11-18): in the browser on the station PC; from elsewhere the name downloads it; program files (`.blocked`) are never opened | built (`tests/test_varalink.py`) |
| **VARA FM digipeaters** (2026-11-18): a path per station (up to two digipeaters) for messages, files and link tests, learnt from the way a station's announcement came or typed by hand; **announce via** for your own announcements; the call waits longer per hop | built; not yet tried through a real digipeater (`tests/test_varachan.py`) |
| **Several copies of VARA on one PC** (2026-11-17): the station reads each VARA folder's TCP port (`varalink.vara_copies`): a new modem is never offered a port another copy uses (Winlink Express's 8300), and "not answering" names the copy set to that port, or says none is | done (`tests/test_varalink.py`) |
| **💾 Radio channels → CHIRP** (2026-11-17): every band-plan channel has **💾+** to put it on your radio list with a short alias (a repeater's callsign or R + its frequency, changeable); reserved ad hoc channels have a **name** (any length) and a **radio alias** (8 characters, for Baofeng and Quansheng displays). The **💾 Radio channels** tab orders them (↑ ↓) and exports one CHIRP CSV for a 2 m / 70 cm handheld or any radio: repeater offset and tone, name in the Comment, other bands left out and named, duplicate aliases named, and two aliases that an older 7-character radio (CHIRP keeps the first 7 on import) would show alike named too. Optionally shared in the ad hoc file (`station/radiochan.py`) | done (`tests/test_radiochan.py`) |
| **VARA channel** (2026-11-16): **Join the channel** announces your call (a VARA CQ frame) and keeps it alive every 10 min while you are at the PC; stations heard are listed here / quiet (grey) / gone; click one to chat or send a file, tick several (or everyone here) for one message to each; quick messages. VARA links one station at a time, so messages queue and go over short links by themselves (⏳ → ✓ sent → ✓✓ delivered); Direct link keeps the by-hand controls (`station/varachan.py`) | built 2026-11-16 against a simulated modem (`tests/test_varachan.py`); **not yet tried on the air** |
| **VARA chat and files** (2026-11-15): on a data radio (Used for: Data (Winlink / VARA)), its column shows keyboard chat and file transfer over **VARA HF or VARA FM** through the VARA modem already on the PC (`station/vara.py`, `station/varalink.py`; the framing is our own published HSK1, docs/VARA.md; a plain VARA terminal gets chat only). Connect, Call CQ, CQs heard, files with progress and a SHA-256 check, Abort. **Transmits only** with the radio's Transmit switch on, the operator at the dashboard and data privileges at the frequency for the license class (band plan); answering calls stops the moment any of that fails; no relay or auto-reply (the channel's keep-alives only while you are at the PC); never encrypted. **Several VARA modems** (2026-11-16): one per data radio, each at its own ports and used for **Chat & files**, **Shared with Winlink Express** (they take turns: the station lets go while Express is open and takes it back when it closes; or hand over by hand) or **Winlink Express only** (never opened); several sessions at once, a log and inbox per radio, a tab per radio, ports never shared; the old single setting becomes a Shared modem. Received files are downloads only | built 2026-11-15 against fake modems (`tests/test_vara.py`, `tests/test_varalink.py`); **not yet tried with a real VARA** |
| **Band plan for your area** (header → **Band plan**, 2026-11-15): one consolidated, reconciled table per band (`station/consolidate.py`): the FCC rules (the **You** column: phone / data / CW for your class), the ARRL band plan, and every local plan **you choose** read into ranges and channels (Nets → Plans → Plans and documents → **In the band plan**, 2026-11-16: `localplans.choose` saves the copy if need be and reads it, one xAI call per document; nothing is read until ticked; nothing is offered or added twice (the same document by address or bytes, the same channel, a plan read again): the state coordinator's band plan, ARES / RACES / ICS-205 / club plans, your own files). Rows are cut at every plan's and every class's edges; the state coordinator's words come first, then local plans, your kept channels, the ARRL's. **⚠** marks plans that disagree, a channel inside a range set aside for another use, and a kept channel (or its repeater input) outside your privileges. Filters (band, only where I may transmit, only what to check, channels), Print; per plan: coordinator / local, in the table or not, read again. A radio's card and Einstein get the consolidated word for its frequency. **Ad hoc voice / Ad hoc VARA** (2026-11-16, `consolidate.open_ranges`): the ranges open for a contact or a VARA session in your privileges, set aside by no plan for anything else, clear of every channel (Winlink gateways included); green **unplanned** on both; **Use** tunes the VARA radio to a VARA range. Bands listed highest first. **Full spectrum** view (every allocation with what is open there for ad hoc voice / VARA). FM bands list free simplex channels (20 / 25 kHz steps); VARA FM narrow vs wide (wide needs ~25 kHz; per-modem Width). Ad hoc VARA FM: plan data segments, plus ARRL local-option / miscellaneous stretches as shared (2 m 145.5–145.8, 1.25 m 223.71–223.85, 70 cm 445–447); FM voice simplex stays voice; a coordinator's band plan decides its area. Reserve ad hoc channels (☆ per channel, ★ in the band plan, 6-character names that fit a Baofeng display), export / import a set or a CHIRP CSV, or send it over a VARA link: the other station gets ★ Install. The station asks for a fresh Winlink Express channel list when one was never downloaded or is over 10 days old (each list optional: Settings → Winlink, or "I don't use…" on the note). Every digit the station speaks on its own says **Niner** for 9. **Tuned now**: each radio's (and VARA modem's) frequency is marked on its row and follows a retune. An open dashboard reloads itself after an install (or offers **Reload** while a pop-up is open) The local-plans search also finds the area's VHF/UHF **Winlink gateways** (into the band plan, untick to leave out). **Winlink gateways from Winlink Express's own channel list** (2026-11-16, `station/winlink_channels.py`): VARA FM / VARA HF channels only, service codes PUBLIC / EMCOMM, distance from each gateway's grid square to the station; VHF/UHF within the search distance into the band plan, VARA HF within 370 mi offered; no xAI cost | built 2026-11-15/16 (`tests/test_consolidate.py`), walked in a browser; not yet run on real plans |
| **Plans** (Nets → Plans, 2026-11-15): **band plan built in** (`station/bandplan.py`: FCC 97.301/97.305 phone, data and CW privileges for every class incl. the 60 m channels, and the ARRL band plan's segments; works offline) and every transmit check uses it (Einstein's voice, VARA data). **Local plans** (`station/localplans.py`): one xAI web search for the area's clubs and EMCOMM groups, the state coordinator's VHF/UHF band plan and the county / section ARES, RACES and ICS-205 plans; every frequency links to its source and is only a proposal until you **keep** it; public plan documents are **saved on this PC** for an outage (members-only ones are never fetched: add your own copy as a file and its frequencies are read the same way); a new search marks what is new and which kept channels left their plan; a plan's regular net goes on the schedule in one click; a radio tuned to a kept channel (or its repeater input) shows its name on its card, and Einstein is told it | built 2026-11-15 (`tests/test_bandplan.py`, `tests/test_localplans.py`), walked in a browser |
| **Find nets: worldwide** (2026-11-15): HF distance up to 20,000 km, and **Also search worldwide**: a third search for DX, international, national-society, maritime, Antarctic / expedition and IARU emergency nets, aimed at the regions, bands and hours **What you can hear around the world today** lists for your antenna, height, power and today's solar flux (17 regions × 160-10 m × 24 hours, free, no AI). Long paths are worked out hop by hop: each hop's own sun (MUF of the weakest hop, daytime absorption summed, the gray line), auroral-oval and polar-cap loss by geomagnetic latitude, the long path round the other side; a net is kept only when you hear it 50%+ of the time when it next meets (the rest are listed as left out, with the figure). DX nets show their region | built 2026-11-15 (`tests/test_netfind.py`), walked in a browser; the model checked against known November openings from the US Midwest |
| **Not heard** (Nets → Schedule): a net listened to 3 times in a row with nothing heard moves off the schedule into **Not heard** (Put back / Forget; an emergency net is only flagged: Move to Not heard / Keep it); Find nets shows a found net that matches one apart and adds it only with **Add anyway** | built 2026-11-14 (`tests/test_fit.py`) |
| **Find nets: HF that works** (2026-11-14): VHF/UHF and HF are two searches run side by side, and searching one keeps the other's results; the search carries the page's current settings (a field still being typed is never lost to the click); HF looks the way an HF operator would (ARRL net directory, section ARES/traffic pages, NTS region/area nets, state/regional emergency and 60 m nets, clubs) for the **kinds you tick**: emergency, traffic, social, technical, special interest; state/regional nets that cover your area are kept even when farther than your distance. **Distance** is computed from each net's town (great circle), not guessed. **HF reach** (station/hfprop.py): hops and takeoff angle from the distance (best of 1-6 hops), the MUF from today's solar flux (NOAA, offline: typical), the **sun over the path when the net next meets** (day/dark, D-layer absorption, F2 lag and decay, winter/summer swing), band noise (ITU-R P.372 slope), and **your antenna's gain at that takeoff angle**: 11 types (flat dipole, inverted V, EFHW, random wire, loop, NVIS, vertical with ground type, delta loop, Yagi, hex beam, whip) from published NEC/ARRL figures, height above ground, power; or **your proven range** ("I hear stations well from 400 to 600 km"), which then defines the antenna's pattern (closer = skip zone). Each HF net shows Hear / Check in with a percentage, distance, hops, takeoff, day or dark, and the full reasoning | built 2026-11-14, walked in a browser |
| **Frequencies remembered** (a radio's Change box): the last 12 frequencies typed for each radio (with their mode) are kept in `data/operator.json` and offered as quick-pick buttons and in the box's dropdown; tap one to fill it in, then Save | built 2026-11-14, walked in a browser |
| **Full screen** (header button): fills the screen with the dashboard; the button (or Esc) leaves it. Hidden where the browser has no full screen (iPhone) | built 2026-11-13 |
| **Nets with no radio, given radios a group at a time** (Nets, `station/netassign.py`): nets kept with no radio on this station (imported with "none", their radio removed, or naming a radio this PC does not have) are listed at the top of Nets, grouped by the radio they used at the other station (an import keeps its name on the net) or by their band and mode, each group with a suggested radio (the same name; else the radio already recording that band and mode; else the only radio tuned to it). **Give them these radios** assigns them all at once; the schedule is saved in `data\settings_backups\` first and nothing is deleted | built 2026-11-13, checked in a browser on a throwaway station (`tests/test_netassign.py`) |
| **Speculative drafting** (`agent.draft(speculate=True)`): Einstein asks its model as soon as a transmission is transcribed instead of after the 1.2 s of quiet it waits for; the draft made after the quiet uses that answer only when its prompt and context are exactly the same (else it asks again), so the model's time overlaps the courtesy wait. A guess for a transmission someone else talked over is dropped (it counts toward the hourly model limit) | built 2026-11-13 (`tests/test_speculative.py`) |
| **Fixed lines kept ahead** (`station/tts.py` `prerender`): when Einstein is on (at station start, and when its name, operator, voice or speed change) the voice clips of the rules' fixed words (check-in, acknowledgement, first-time introduction, the transmitter test) are made and kept in the chosen voice, so the first check-in on the air does not wait on the voice service; quiet with no key or no internet | built 2026-11-13 |
| **Tools for the thinking model** (`station/toolbox.py`, `agent.call_xai_tools`): with xAI, a deep answer and the private chat no longer get the library and path analyses pasted in as context; the model calls `search_library`, `list_sites` and `path_analysis` itself (up to 4 rounds, results bounded, failures returned as text), then gives its answer in the fixed schema. Other providers keep the pasted context. Each chat answer and each deep answer shows what it looked up ("looked up: the library, a path analysis") | built 2026-11-13, tested with a scripted xAI (`tests/test_toolbox.py`, `tests/test_topics_chat.py`) |
| **AI costs** (Settings → AI costs): every paid AI call in a ledger (by feature: today, 7 days, month, last calls; xAI's own cost per answer, else its price list), an optional monthly budget per station (warning at 80%, background AI paused at 100%), **Buy credits** / Usage links, an "out of credit" warning, and with an optional xAI management key the account's credit left and month's spend from all stations plus a low-credit warning (read only, never a top-up) | built 2026-11-14 (`station/aicost.py`, `tests/test_aicost.py`) |
| **Settings in tabs**: Station, Nets, Winlink, Einstein & AI, AI costs, This PC, Share; one row per setting with one plain line (the long explanations behind **Why?** / **How it works**); each section says how it saves (**Save below**, its own button, or at once); the Save bar names what changed, marks its tab, and puts a refused field's error beside it; closing with unsaved changes asks first | built 2026-11-15 (`station/static/index.html`, `tests/test_station.py`) |
| **Net summary** at the top of the minutes: the station's own lines (who took part, newcomers, urgent, traffic, announcements, action items, decisions) and Jump to links; with the xAI key, an AI-drafted paragraph by default (Settings → *AI summary at the top of each net's minutes* turns it off), written about 10 minutes after the net, Edit / Rewrite / Remove. The Summary leads the .md / text export and the ICS-213 | built 2026-11-14 (`station/netsummary.py`, `tests/test_netsummary.py`) |
| **Help: six reference cards** (the dashboard's **Help**: *The station*, *Einstein, the AI assistant*, *Record a conversation*, *VARA chat and files*, *Band plan for your area* (2026-11-15), *Ad hoc channels* (2026-11-16); each card links the others; `/help`, `/help/sidekick`, `/help/conversation`, `/help/vara`, `/help/bandplan`, `/help/adhoc`): the Einstein card rewritten around using it (the Off / Draft / Send switch, what it does by itself, What would you say now?, Chat, Prepared talks, Library and Sites; set up once on the back), and a new card for recording a contact outside any net (listening, Change, End conversation, Completed / History / Search, Minutes, Winlink messages). Outside a net the End button now says **End conversation** | built 2026-11-13; the operator walkthrough covers all three cards (sandbox: 37 pass, 0 fail) |
| **Einstein card** (two sides, US Letter) | Using Einstein: its switch, its turns, chat and prepared talks, sending, set up | **[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Assistant_Quick_Reference_Card.pdf)** |
| **Conversation card** (two sides, US Letter) | Recording a contact outside a net and finding it afterwards | **[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Conversation_Quick_Reference_Card.pdf)** |
| **VARA card** (two sides, US Letter) | Keyboard chat and file transfer over VARA HF / FM: one modem per data radio, connect, files, taking turns with Winlink Express | **[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_VARA_Quick_Reference_Card.pdf)** |
| **Band plan card** (two sides, US Letter) | Finding your area's band plans and EMCOMM plans, and reading the consolidated band plan | **[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Band_Plan_Quick_Reference_Card.pdf)** |
| **Ad hoc channels card** (two sides, US Letter) | Where ad hoc VARA FM and FM voice may go on 2 m / 1.25 m / 70 cm; reserving, naming (a name and an 8-character radio alias), sharing and programming your channels with CHIRP | **[Open the PDF](docs/HAM_Sidekick_Ad_Hoc_Channels_Quick_Reference_Card.pdf)** |

The same ZIP is on this page under the green **Code** button → **Download ZIP**.

---

## Install

1. **Download** the [ZIP package](https://github.com/travislhilton/hamsidekick/archive/refs/heads/master.zip) and save it anywhere.
2. **Unblock** — right-click the ZIP → Properties → tick **Unblock** → OK *(skip it if there is no Unblock box)*.
3. **Extract** — right-click the ZIP → **Extract All** → Extract.
4. **Run the installer** — in the extracted folder open `install` → `windows` and double-click **`install.cmd`**. Press **Yes** when Windows asks for administrator rights. If Windows shows "Windows protected your PC", click **More info** → **Run anyway**.
5. **Type your callsign** when asked. Press **Enter** to skip the QRZ.com question if you don't use QRZ (you can add it later).
6. **Keep the PC plugged in and leave it alone while it measures.** The installer measures how fast this PC transcribes, with the screen held on (a laptop with its screen off runs several times slower and would get a slower setup).
7. **Choose when the station may change your power settings** (it asks once; press **Enter** for the recommended choice). While it transcribes, the station keeps the screen on and switches to its own **HAM Sidekick Station** power plan at Best performance, then puts your own plan back. Settings → *Full speed and screen on* changes it later.
8. **Wait for `== Done`.** The first install downloads about 4 GB (Python packages, Whisper speech models, the FCC license database) and takes 10–30 minutes. It ends with **This PC**: anything in your power settings that would slow the station (on battery, power-saving mode, hibernate, an old graphics driver, a quiet fan profile), each with its fix. Then it lists the sound inputs this PC can record from: note your radio's.

**Internet is needed for the first install only.** The station itself works with none.

**To update:** download the ZIP again and run `install.cmd` again. Everything you set is kept: radios, net schedule,
settings, local names, learned fixes, keys, QRZ login, logs and history (they live in `data\` and the station's own
config files, which an update never overwrites). The earlier speed measurement is kept too; `install.cmd -Remeasure`
or **Settings → This PC → Measure this PC again** measures again (after new graphics drivers or a new PC).

### What the installer does

`install/windows/install.ps1`, safe to re-run. Nothing needs to be installed beforehand:
- checks the PC first (64-bit Windows 10/11, about 8 GB free, internet for the first install) and says what is missing;
- installs the Microsoft Visual C++ runtime if it is missing (OpenVINO, PyTorch and faster-whisper need it);
- installs Python 3.12 for all users (winget, or straight from python.org when winget is missing) and a private
  environment in `C:\HAM-Sidekick-Station\.venv` with every Python package the station uses;
- downloads four Whisper models in Intel OpenVINO format (three for the live text, Whisper large-v3 for the
  accurate pass; plus faster-whisper large-v3 on a PC with an NVIDIA card) and **benchmarks this PC** to choose the
  live engine (`tools/pick_engine.py` → `config/engine.yaml`): Intel graphics, NVIDIA (CUDA) or CPU;
- **measures what this PC can do for the accurate pass on its own** (`tools/pick_accurate.py` → `accurate:` in
  `config/engine.yaml`): each accurate model on each device (Intel GPU, CPU; NVIDIA; not the NPU, see below), then decides *both
  stages* (fast enough to follow every transmission), *final text only* (after each net) or *none*;
- downloads the FCC amateur license database and the world country file, and schedules a daily
  update (task "HAM Sidekick Callbook Update", 04:15, only when online);
- asks (once, optional) for a QRZ.com login: Enter skips it. It checks the login and says in plain words what the
  account gives (full records need QRZ's "XML Logbook Data" subscription; without it only names and countries; US
  callsigns are covered by the FCC database either way). The password goes to Windows Credential Manager;
- reports the graphics card and driver (Intel/NVIDIA graphics are used only with a current driver);
- keeps your settings (`config/station.yaml`, `config/engine.yaml`, `config/local.yaml`) across updates;
- starts the station at every sign-in (task "HAM Sidekick Station", which also brings it back within 2 minutes if it
  ever stops), puts a **HAM Sidekick Station** shortcut on the
  desktop, and opens port 8091 to your home network and Tailscale only;
- lists the audio inputs it can record from.

**On a laptop:** keep it plugged in, set the maker's performance profile to **Performance** (ASUS: MyASUS → Fan
Profile), turn off *Turn off my screen when I leave* (Settings → System → Power & battery → Presence sensing) and never
let it hibernate on mains power. Laptops with Modern Standby slow to about a fifth of their speed once the screen is
dark, so while the station transcribes it holds the screen on and switches to its own **HAM Sidekick Station** power plan,
then puts yours back. **Settings → This PC** shows what it changes and anything that slows this PC. The details:
[On a laptop](docs/MANUAL.md#on-a-laptop).


**No good internet?** `install.ps1 -ModelsFrom D:\models` copies the Whisper models from a folder you already have (another station's `models` folder, a USB drive, a network share) instead of downloading about 2.6 GB.

**Start over without losing anything.** `tools\settings_bundle.ps1 -Backup <zip>` keeps your settings (net schedule, radios, Einstein,
local names, keys) in one file and `-Restore <zip>` puts them back; `tools\uninstall.ps1 -MoveAside` removes the program, its tasks and
shortcut but leaves your folder (with history and recordings) beside the new install. Run them in PowerShell **as administrator** from the
extracted ZIP, then run the installer again.

---

## After installing — what to do

1. **Open the dashboard:** double-click **HAM Sidekick Station** on the desktop (or browse to `http://localhost:8091/`).
   The station starts by itself whenever you sign in to Windows.
2. **Add your radio:** **Radios…** at the top → **+ Add a radio** → a name, its **sound input**, where its audio comes
   from (*speaker / earphone jack or SSB*, or *FM data jack*), mode and frequency → **Save and restart the station**.
   An Icom IC-705: also choose its **CAT port** (computer control), so the station reads the frequency and tunes the
   radio for its nets. Details: [Connecting a radio](#connecting-a-radio).
3. **Set the level:** **Set level…** on the radio's card walks you through the radio's volume and squelch until the
   station hears it cleanly.
4. **Add your nets:** **Nets** → **+ Add a net**: name, radio, start, length, frequency, net control and how it
   repeats (every Tuesday, 1st and 3rd Sunday…). Five minutes before each one a yellow alert tells you what to set.
   A transmission counts as the net's only when the radio is on the net's frequency.
5. **Open it on your phone** (optional): **Open on phone** at the top → point the phone's camera at the code (same
   Wi-Fi as the PC, or Tailscale).
6. **Settings** (optional): your name, grid and Winlink Express account (for the Winlink messages), a QRZ.com login,
   your area's local names, and an xAI API key for **Einstein**, a station assistant that drafts what your station
   could say on the net and never transmits.
7. **Print the [Quick Reference Card](#quick-reference-card)** and keep it by the radio.

### After the net: Winlink messages

When net control closes the net (or you press **End net**) recording stops and the accurate pass re-reads the net.
Press **Winlink messages…** on the net's header: you get an **ICS-309** communications log and an **ICS-213**
summary, titled with the net's name. Check the To: list (stations the callbook can't confirm start unticked), read
and edit the messages, **close Winlink Express**, press **Put in Winlink Express Outbox**, then open Winlink Express
and connect. They go out with your next session.

**Winlink Express on another PC:** under **Put them in the Outbox on**, choose that PC instead of the station. Install
the Winlink helper there once: open the dashboard in a browser on that PC, Winlink messages… → **get the helper for
this PC**, and run the downloaded `install-winlink-helper.cmd` (no administrator rights; it gets its files from the
station, installs Python 3.12 for you if needed and starts at every sign-in). The helper asks the station for
messages every few seconds and writes them into that PC's Outbox, with Winlink Express closed there, as on the station.

## Running a net

**The screen.** The navy bar at the top is the station: your call, the net on the air, the clock (local and UTC),
**● Live text** (the speech engine is ready) and **● Home server** (where the better second reading is made, see
below), **Search everything**, and the buttons **Nets**, **Radios…**, **Settings**, **Open on phone**,
**Read-out**, **☾ Night** and **Help** (the reference cards: the station, Einstein, recording a conversation, VARA chat and files, the band plan, ad hoc channels). Below it, one column per radio: its nets today, its
card (frequency, Signal and SNR meters, waterfall, **Change**, **Pause**, **Set level…**), and its log. On a phone
the radios are tabs.

**Before the net.** Five minutes before, a yellow alert says what to set ("set the FTM-150R to 146.940 MHz FM").
Tune the radio and press **Radio is set** (a radio with CAT tunes itself). A transmission counts as the net's only
when the radio is on the net's frequency, so if you retune, press **Change** on the card.

**During the net.** Each transmission appears a few seconds after the station unkeys: grey words while it is still
talking, then the text. The callsign at the start is **who is talking** (bold = they said it; ≈ grey = probably net
control; blank = not known: press **Who?**). Tap any callsign for its license card. **✎ Fix** corrects a line (the
minutes, search and Winlink messages use your text). **Coach** (a tab on the radio's card) says what to do when
someone asks for a relay or calls emergency traffic; a red **Urgent** box keeps anything urgent in view. **Stations
heard** lists every call with name and town. The **Net board** tab on each radio shows who is in (numbered), who to ask again, who has traffic,
regulars not heard yet, and when net control last said its call.

**After the net.** When net control closes the net (or you press **End net**), the station re-reads the whole net
for better text and drafts the **minutes** (attendance, announcements, action items, traffic). Then
[After the net: Winlink messages](#after-the-net-winlink-messages). Open the **Net board** tab (or the minutes' Attendance) and **review the check-ins**: ▶ listen, ✓ right,
✎ the right call, ✗ not in the net. About half the calls the station hears only once are mis-heard; your marks fix
the minutes and the Winlink messages.

**At night.** **☾ Night** (top right) turns the whole screen red on black to keep your night vision; press it again
for normal colours. **Settings → Display** chooses Automatic / Light / Dark / Night and a 24-hour or 12-hour clock
(per browser). The colours match the companion EMCOMM forms' EOC Message Center.

Every feature in detail: [the manual](docs/MANUAL.md).

## Chat and files over the radio (VARA)

Keyboard chat and file transfer between stations, radio to radio, through VARA (no internet, no Winlink server).
The full detail is in [the manual](docs/MANUAL.md) (VARA chat and files) and the protocol in [docs/VARA.md](docs/VARA.md);
the [VARA card](#quick-reference-card) has it on two printed sides.

**What you need.** A radio for data with its own sound interface and PTT (a Digirig, a SignaLink, an IC-705's USB),
and VARA FM (VHF/UHF) or VARA HF installed and set up for that radio, as for Winlink. Each station on the channel
uses its own call with an SSID (W9XYZ-7 here, K7ABC-8 there).

**Set it up once.**
1. **Radios…** → the radio → **Used for: Data (Winlink / VARA)**, with its **Transmit** switch on. Its column on the
   dashboard becomes its **VARA workspace**: the stations on the channel, the chat and the files, under the radio.
2. **Modem setup…** under the radio: VARA's TCP ports (8300 is Winlink Express's own VARA), your **call** for this
   modem, and its job: **Chat & files** (this station only), **Shared with Winlink Express** (they take turns: the
   station lets go while Express is open) or **Winlink Express only**. A second copy of VARA in its own folder (for
   example `C:\VARA FM 2` on ports 8310/8311) lets one radio do Winlink and another do chat.
3. Put both stations on the same frequency: **Band plan → Ad hoc VARA** lists the ranges open to you for data, and
   **Use** tunes the radio there.

**On the channel.**
- **Join the channel** announces your call and repeats it every 10 minutes (VARA HF 15) while you are at the
  dashboard. Stations heard are listed **● here**, **○ quiet** (grey) or **Earlier**.
- **Chat:** click a station, type, Enter. VARA links one station at a time, so each message waits its turn (**⏳ queued**,
  shown as such while the frequency is busy, for example with a file), goes out over a short link when the
  frequency is clear (**✓** sent, **✓✓** delivered), and the link is let go after 20 s of quiet. **Keep the link
  open** for a back-and-forth. Tick several stations, or **Select everyone here**, to send one message to each.
- **Send a file:** choose the station, **📎 Send a file…** (up to 5 MB). You are told about how long it will take
  before it goes. While it is on its way **both** stations show it in the chat and at the top of the panel: percent,
  size, transfer rate, time left and how long the frequency stays in use. **Cancel** works on either end; the other
  end's chat says who cancelled and how much had arrived, so a cancel is never mistaken for a link failure.
- **Receive a file:** nothing to press. It appears in the chat as a 📎 link and under **Files received**; on the
  station PC **Open** opens it (it asks first) and **Show in folder** shows where it was kept. Program files are
  given a `.blocked` ending and are never opened from the dashboard.
- **Test link speed** (under the chat, 30 / 60 / 120 s, on demand): VARA starts slow and steps up as data flows,
  so the test measures the real speed reached and gives a table of **how long a 1 KB to 1 MB file would take** to
  that station. Check the frequency is clear first: the test uses it for that long.
- **Digipeaters (VARA FM):** when a station is out of reach, **🛰 Path to …** sends through up to two VARA FM
  digipeaters; a path is learnt by itself from the way a station's announcement came. **Announce via** sends your
  announcements through one too.

**When it transmits.** Only while you are at the dashboard (page open and in front, within the last 3 minutes),
with the radio's Transmit switch on and data privileges for your licence class at that frequency; the panel says
why when it will not. Everything is sent in the clear, as Part 97 requires: no encryption.

## The home server (optional)

A station works on its own. A **home server** (a Mac with Apple silicon on the same network or Tailscale, running
`transcribe/`) adds a better second reading of each transmission with a larger Whisper model: the **accurate pass**.
The top bar says where it is made:

| Top bar | What it means | What you do |
|---|---|---|
| **● Home server** (green) | The home server answers; each transmission gets better text within seconds | Nothing |
| **● Accurate on this PC** (amber) | The home server is not reachable; this PC makes the better text itself (after each net if it is not fast enough to follow every transmission) | Nothing; it goes back to the home server by itself |
| **● Home server offline** (amber) | The home server is not reachable and this PC cannot do the accurate pass: it waits | Nothing for the net; the text comes when the server is back |
| (none) | No home server set up, and this PC does not do it | Nothing: the live text is what you get |

**The live text never depends on the home server**: it is made on the station PC and carries on whether the server
is there or not. The station checks the server every minute; when it comes back, whatever waited is sent at once.
If the server goes away in the middle of a net, the rest of that net's work moves to this PC (or waits) without
holding up the live text. The Winlink messages use the best text there is: your corrections, then the accurate pass,
then the live text. Setting one up: [Home-network server](docs/TECHNICAL.md#home-network-server-optional).


## Quick Reference Card

Two sides on one sheet: **Install and Get Started** on the front, **Running a Net** on the back. Same layout as the
Church of Jesus Christ EMCOMM quick reference cards. Print it double-sided ("flip on long edge"), laminate it, and
keep it by the radio. Works in black and white.

**[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Station_Quick_Reference_Card.pdf)** ·
[view it on GitHub](https://github.com/travislhilton/hamsidekick/blob/master/docs/HAM_Sidekick_Station_Quick_Reference_Card.pdf) ·
on the station: **Help** (top right of the dashboard) opens the same card; the browser's Print prints it.

**Einstein card** (two sides: using Einstein, then its card, sending and set up):
**[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Assistant_Quick_Reference_Card.pdf)** ·
on the station: **Help → Einstein, the AI assistant**, **Settings → Einstein & AI → Station agent → Einstein card**, or **Card** on Einstein's card on a radio.

**Conversation card** (two sides: recording a contact outside any net, then finding and using it):
**[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Conversation_Quick_Reference_Card.pdf)** ·
on the station: **Help → Record a conversation**.

**VARA card** (two sides: setting up your VARA modems, then contacts, chat, files and taking turns with Winlink Express):
**[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_VARA_Quick_Reference_Card.pdf)** ·
on the station: **Help → VARA chat and files**, or **Card** beside VARA chat and files under a data radio.

**Band plan card** (two sides: finding the area's plans and keeping channels, then reading the band plan):
**[Open the PDF](https://cdn.jsdelivr.net/gh/travislhilton/hamsidekick@master/docs/HAM_Sidekick_Band_Plan_Quick_Reference_Card.pdf)** ·
on the station: **Help → Band plan for your area**, or **Card** in the Band plan window and on Nets → Plans.

**Ad hoc channels card** (two sides: where you may go ad hoc on 2 m, 1.25 m and 70 cm; then reserving, naming, sharing over a file or VARA, and putting the channels in a radio with CHIRP):
**[Open the PDF](docs/HAM_Sidekick_Ad_Hoc_Channels_Quick_Reference_Card.pdf)** ·
on the station: **Help → Ad hoc channels**, or **Ad hoc channels card** in the band plan's Ad hoc tabs.

The card's QR code opens this download page. A club handing out its own copy sets `download_url:` in
`config\station.yaml` and the card the station prints carries that address instead. To rebuild the PDF after
editing `station/static/card.html`: `python -m tools.build_ref_card` (needs Google Chrome; it fails when a side no
longer fits one page).

**Business card** (to hand out; kept in the Church of Jesus Christ EMCOMM project, so both projects share one card): HAM Sidekick Station on one side, Church of Jesus Christ EMCOMM on the other, each with a QR code to its page; 10 per sheet on **Avery 5371**. **[Open the card page](https://travislhilton.github.io/church-emcomm-wnlk-forms/training/handouts/business-card-avery-5371.html)** (Print, an alignment test and nudge boxes to line up your printer) · [PDF](https://travislhilton.github.io/church-emcomm-wnlk-forms/training/handouts/pdf/Business_Cards_Avery_5371.pdf): print two-sided at **Actual size**, flip on the long edge; try plain paper first. On the station: **Business card ↗** at the top of every Help card (needs the internet).

## When something looks wrong

| You see | Do this |
|---|---|
| No text at all | Is the radio **Paused**? Does the Signal meter move? Does the squelch open on traffic? Run **Set level…** on its card |
| The same words for every transmission, or "The." over and over | The live engine is stuck: the station checks and reloads it while a dashboard is open. If it carries on, run **Test transcription…** on the card, or restart the station (sign out and back in) |
| "Its sound input … is not there" on a radio's card | The audio cable is unplugged, or (IC-705 on Wi-Fi) Icom Remote Utility is not running. **Choose its input…** picks another |
| The meter is red / shows nothing | Too loud: turn the radio's volume down. Nothing: check the cable and the radio's input in **Radios…** |
| The wrong net name on the log | Is the frequency on the radio's card what the radio is on? **Change** it |
| **● Home server offline** at the top | Nothing for the net: the live text carries on. See [The home server](#the-home-server-optional) |
| **🔒 Close Winlink Express first** in Winlink messages | Close Winlink Express; the button turns green (**✓ Put in Winlink Express Outbox**) within 2 seconds |
| The page won't open | Sign in to Windows on the station PC (the station starts at sign-in). A phone: same Wi-Fi or Tailscale |
| A slow-transcription warning | Plug the laptop in, wake the screen, check **Settings → This PC** |


## Connecting a radio

Each radio needs its receive audio on a PC sound input of its own (never the one a digital mode
such as VARA FM uses). Give that input a clear name in Windows (Windows 11: Settings → System → Sound → the input →
Rename; or `Win+R` → `mmsys.cpl` → Recording → the device → Properties), e.g. `NET-REC`: two identical adapters (one
for the net, one for Winlink) can then be told apart.

**Radios…** (top of the dashboard) adds, replaces or removes a radio: a name, its sound input (chosen from the inputs
plugged in), where its audio comes from (*speaker / earphone jack or SSB* = voice gate, squelch closed; *FM data
jack* = carrier gate, hiss always on), mode and frequency. Saving restarts the station (about 15 s, the page
reconnects). Once saved there, the list lives in `data\radios.json` and `station.yaml`'s `radios:` is no longer read
(delete the file to go back); meter and segmenting settings from `station.yaml` are kept per radio id. Inputs can change
under a running station (renamed in Windows Sound settings, re-plugged, a driver update that makes new ones): the
list in Radios… is always read fresh, a radio whose input comes back reconnects by itself within about a minute, and
a radio whose input is gone says what Windows did with it and offers **Choose its input…**. A radio with
nets cannot be removed until its nets move to another radio. Inputs are matched exact name first, so a radio on
"Digirig Lite" never opens "Digirig Lite NET-REC". Then use **Set level…** on its card.

**Transmit (PTT), set up but switched off.** Each radio in **Radios…** has a **Transmit (PTT)** section: how the
station would key the radio — **Sound card GPIO** (what VARA FM calls *RA-Board*: Digirig Lite, AIOC, CM108/CM119
interfaces, pin 3), or a serial **RTS / DTR** line on its own COM port (never the CAT port) — the **Audio out** the
transmitted voice goes to, and a **time limit** (5-180 s, default 60) after which the transmitter is let go whatever
happens. **Allow transmitting on this radio** is OFF by default; while it is off nothing can key the radio. Only Einstein's Send mode and the **Transmit test…** (into a dummy load) key it; also **Drive level**, **Lead** and **Tail**. A voice transmission
needs a control operator at the station (FCC 97.109) and your call sign (97.119). The GPIO is reached through
`hidapi` (installed with the station).

| Radio | Interface | Notes |
|---|---|---|
| A handheld (Baofeng, Wouxun KG-UV9PX+, …) | speaker/earphone jack → Digirig Lite or Mobile (USB) | Audio from: *speaker / earphone jack* (voice gate). The jack is very loud: Set level… step 1 finds the cleanest volume knob position. On all day: run it from a charger or battery eliminator — a flat battery shows as **the radio seems to be OFF** on its card. |
| Yaesu FTM-150R (VHF/UHF) | DATA jack (10-pin mini-DIN) → Masters DRA-50M (USB) | Set 45 DATA BAND = A-BAND FIX, tune band A to the net; leave 41 DUAL RECEIVE MODE (a priority scan) OFF. The DATA jack is unsquelched, so the recorder's **carrier gate** detects transmissions from the drop in hiss. Step by step: `docs/FTM-150R-SETUP.txt`. |
| Icom IC-705 (HF/VHF/UHF, Wi-Fi) | Icom **Remote Utility** (connected to the radio) → its virtual sound input `IC-705 (Icom Virtual Audio Driver)` | In `station.yaml`: `device: IC-705`, `gate: voice` (SSB has no carrier to detect). Remote Utility must be running and connected. **CAT** (optional, recommended): in **Radios…** choose the radio's **CAT port** — Remote Utility's virtual CI-V COM port on Wi-Fi, the radio's first COM port on USB (CI-V address A4). The card then shows the frequency read from the radio, **Change** tunes the radio, and each of its scheduled nets tunes it (any band) and puts it back after. |

## Incident read-out (situation report on a voice net)

The station can read an EOC's situation report on a voice net — from the companion EOC Message Center
(`GET http://<eoc>:8080/api/readout`) or a file carried by hand. The shared format is `contracts/emcomm-readout/`
(`emcomm-readout/1`, JSON Schema + example fixtures). Open **Read-out** in the dashboard header (or `/readout` on a phone):

1. **Get from the EOC** or **Load a file**. A document that carries injuries, deaths, missionary status or details
   about people is refused, not filtered: those are never read on an open frequency.
2. The facts and a voice script written by a fixed template (no AI): sections of about 30 seconds, numbers in words,
   the call sign at the end of each section, "This is an exercise" around each section during a drill.
3. **Approve**: by the Stake President or his delegate (stake and satellite EOCs) or the Area Authority or his
   delegate (area EOC). The approval binds to the report's fingerprint; a newer report with different facts needs a
   new approval and shows what changed.
4. **Read on the air**: a large-type card, one section at a time. The operator keys the radio and reads in their own
   voice; the station never keys a transmitter. Reading it is logged (`data/readouts.jsonl`) and noted in the minutes
   of the net that is on.

## Requirements

| Requirement | Notes |
|---|---|
| **Windows 10 or 11, 64-bit** | The station PC. About 8 GB free; a laptop works (keep it plugged in). Windows 11 on ARM (e.g. a VM on an Apple silicon Mac) works too: OpenVINO does not run there, so the installer picks faster-whisper on the CPU (small.en, about 0.4x real time in a VM; no words while someone is still talking) |
| **A sound input per radio** | A USB sound card or interface (Digirig, SignaLink, a data-jack cable) — never the one VARA or Winlink uses. An IC-705 on Wi-Fi uses Icom Remote Utility's virtual sound input |
| **Internet, the first time** | About 4 GB for the install. Afterwards the station works with none |
| **Winlink Express** | Only to send the net's messages by Winlink · [winlink.org](https://winlink.org) |
| **VARA HF or VARA FM** (optional) | Only for keyboard chat and files over the radio: the modem from [rosmodem.wordpress.com](https://rosmodem.wordpress.com), with the data radio's own sound interface and PTT (Digirig, SignaLink…). VARA's free version is limited in speed; a licence key (from its author) unlocks the full speed and digipeating. The other station needs HAM Sidekick Station for files; any VARA keyboard program can chat |
| **Intel or NVIDIA graphics** (optional) | Faster text with a current driver; the CPU works too. The installer measures this PC and picks |

## Your own settings stay on your PC

Everything personal is kept in files the repository never contains (they are git-ignored and the installer
never overwrites them): your callsign, name and grid and the radios in `config\station.yaml`; your area, repeaters
and roster in `config\local.yaml`; the accurate-pass server's address in `station.yaml` (`accurate: urls:`) and its
key in `config\secrets.env`; your own **xAI API key** for Einstein, its voice and Grok speech-to-text (optional: **Settings → Einstein & AI → Station agent**,
paste it and **Save key**; **Test** asks xAI whether it works; the page only ever shows "set …abcd"; it is kept in
`config\secrets.env` as `XAI_API_KEY=…`, readable only by the station's user, SYSTEM and Administrators — create one at
console.x.ai → API Keys after adding a little credit under Billing; optionally an **Anthropic API key** the same way,
to compare Claude Haiku with Grok); the QRZ.com password in Windows Credential Manager; SSH public keys for remote
management in `deploy\windows\ssh-keys.txt`. The server keeps its settings in `~/.config/emcomm-stt/env`.

## How long recordings and net history are kept

**6 weeks by default; Settings → Keep recordings and net history for … weeks** (1–104; `keep_weeks:` in
`station.yaml` is the starting value, the dashboard's choice wins). A busy two-radio station records about 130 MB a
day. Every 6 hours (and 10 minutes after the station starts; never while a radio is receiving or transcribing) the
station deletes whole days older than that (`station/retention.py`): the recordings (`data\recordings\<day>`), the
day logs (`data\logs`), those days' nets, transmissions, who took part, minutes and items in the history database
(then compacted), voiceprints, the station agent's drafts and Grok comparisons. A net that started before the first day
kept goes whole. Shortening the time asks first and deletes about a minute after you save. It also keeps two
caches in check: a removed radio's leftover raw audio (over a day old) and OpenVINO's compiled models (over 3 GB, the
least recently used over 2 days old go; every re-measure adds about 1.8 GB), and cuts `data\station.log` to its last
2 MB at start once it passes 10 MB. **Never deleted:** settings, radios, the net schedule, local names, learned
fixes, keys and the callbook. Settings → This PC shows the disk used, the oldest day kept and the last cleanup.
`python -m station.retention --dry-run` lists what would go.

## The full manual

[docs/MANUAL.md](docs/MANUAL.md): every feature (the log, Who?, corrections, local names, search, the nets window,
minutes, Winlink, the end of a net, HF scan, Einstein, the urgent board…). [docs/TECHNICAL.md](docs/TECHNICAL.md):
segmenting, the accurate pass, the home server.

## Support, feedback and bug reports

Found a problem, or have an idea? Anyone with a GitHub account can **[open an issue](https://github.com/travislhilton/hamsidekick/issues/new)**: say what you did, what you saw, the radio and interface, and the time of the transmission. Please don't post recordings of other operators' transmissions or their personal details.

## Contributing — developing this project

```bash
python3 -m venv .venv && .venv/bin/pip install -r transcribe/requirements.txt -r analyze/requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest -q
```
Design: `docs/ARCHITECTURE.md`, including which settings live in which local config file. Your callsign,
server addresses, keys and logins go only in those files (`config/station.yaml`, `config/local.yaml`,
`config/secrets.env`, `capture/config.yaml`, `~/.config/emcomm-stt/env`); git ignores them.

## Status

| Piece | State |
|---|---|
| Live signal + SNR meters and waterfall per radio; several radios at once | working |
| A silent radio is flagged on its card and in station.log: a handheld switched off / asleep / flat (input dead flat ≥ 3 dB under its own learned squelch-closed floor for 2 min), a data jack with no hiss (2 min), or a net on the air with nothing heard for 10 min (`station/silence.py`, per radio `silence:`) | working: replayed on the hour a handheld died (flagged 2 min after, cleared when switched on; no false alarm on the squelch-closed gaps) |
| **Morse code (CW)** on any radio, any frequency: a keyed tone in the continuous audio (not only gated transmissions) is decoded and shown in the transcript as **CW · Morse code** with its speed and tone, the dots and dashes as heard, then the text (→ CQ DE W9XYZ K); prosigns as <AR>, <SK>, <BT>, <KN>; ▶ plays it. Heard during a voice transmission it is added to that transmission; alone it is a row of its own (logged, searchable, callsigns picked out; never sent to the accurate pass). Counted as Morse only when the timing sits on Morse's 1:3:7 grid, the tone is steady and at least 3 characters decode (`station/morse.py`; `morse: false` per radio turns it off) | working on synthetic CW (5–50 wpm, 0 dB SNR, 15 % hand-keyed timing jitter, prosigns); no false detections in 76 min of real and synthetic voice (460 recordings), a steady carrier, courtesy beeps, DTMF or sub-audible tones; first on-air CW to be confirmed |
| Radios… on the dashboard: add / replace / remove a radio, sound input chosen from those plugged in (exact name first), station restarts itself | built 2026-11-05 |
| Inputs that change under a running station: fresh input list, self-reconnect when an input comes back, "Choose its input…" on a radio's error, and what Windows did with a missing input (a driver update's new input on the same USB port) | built 2026-11-07 |
| Set level… per radio: noise and voice against a target, Windows recording level read/set, Adjust automatically | working (handheld's speaker jack into a Digirig: -13 dBFS clipping → -24 dBFS in one step) |
| Recording per transmission (carrier gate for FM data jacks; voice gate otherwise) | working, tested on the FTM-150R |
| Weak-signal repetition guard (Whisper loops) | working |
| Repeaters / carrier that stays up between speakers: split at speech pauses (>= 0.8 s) and carrier dips, cut in the middle of the pause, a fragment ("Over.", the end of a call sign) kept with its neighbour, a voiceless repeater tail never its own transmission | working (`split_pause_ms`, `dip_split_ms`, carrier-gate radios; see "Segmenting"); 2026-11-03 FM net replayed: 140 → 105 transmissions, blank ones 31 → 3, words lost in dropped pieces 79 → 0 |
| **Einstein** (the station agent, Draft mode): operator-named (call-like names refused), two speeds (quick model per turn; a thinking model for a question, announced "response ready" when net control gives the floor, read word for word when told to go ahead), offline rules (check-in, acknowledge, announce/read a prepared answer), memory across a restart, local names in its context, FCC Part 97 checks in code | built + unit-tested 2026-11-10; offline rules replayed on a real 280-transmission FM net (one check-in, at "next station, please" in open check-ins; silent for city/EOC/county calls); the models on real nets: see the replay |
| Einstein's voice: xAI TTS audition of every voice, chosen in Settings, ▶ Hear it on drafts (browser only, never a radio) | built + unit-tested 2026-11-10 |
| Grok speech-to-text compared live on chosen radios (never queued; skipped offline/busy/over the minutes), Compare today, `tools/grok_compare.py` | built + unit-tested 2026-11-10 |
| Voice gate on squelched FM: the pre-roll reaches back to where the squelch opened (up to 2.5 s; the 11-10 roll call lost the first letters of 60% of its calls to a late VAD) | built + unit-tested (`squelch_db`), 2026-11-10; measured on the next squelched-FM net |
| Far call one rhyming letter from a licence within 50 km: not counted, the near ones offered (never moved); a net's own **Reach (km)**; PO-box ZIPs placed by region (far only); a net edit keeps its repeater offset/tone | working (`station/consensus.py`, `hamkit/zipgeo.py`), 2026-11-10 |
| HF / voice gate: 600 ms pre-roll; a short piece waits 0.6 s after the hangover for its continuation (a call sign spelled with gaps, a kerchunk before the words) | built + unit-tested (`merge_gap_ms`, `merge_max_s`, `preroll_ms`); not yet measured on a live HF net |
| Sub-audible tone + mains hum removed before Whisper (high-pass 300 Hz on FM data-jack radios) | working (`highpass_hz`) |
| Whisper's noise phrases ("So.", "We'll be right back.") shown greyed as probable noise, left out of the ICS-309 | working |
| Icom IC-705 via Icom Remote Utility (voice gate) | working on the test PC |
| **Transmit (PTT) setup** per radio (Radios… → Transmit; `tx: {ptt: cm108, hid, pin: 3, out, max_s, enabled: false}`): sound-card GPIO (VARA's RA-Board) or serial RTS/DTR, audio out, time limit with a watchdog; refused unless **Allow transmitting** is on (off by default); nothing calls it yet (`station/ptt.py`) | built + tested with simulated interfaces; no key-up on a radio yet |
| **CAT control (Icom CI-V)** per radio (`cat: {port: COM11, civ: A4}`, or Radios… → CAT port): the frequency and mode are read from the radio every 5 s (card + every transmission); **Change** tunes the radio; a scheduled net on that radio — VHF/UHF or HF — tunes it at the net's start (frequency, mode, tone squelch off; the net's repeater offset and tone when it gives them) and puts back what it was on when the net ends, unless the operator retuned during the net (kept across a restart). Never transmits: only reads and these settings can be sent (`station/cat.py`) | built + tested on a simulated IC-705 (CI-V echo, HF/VHF/UHF, restart mid-net, missing port); first test on the radio pending |
| Live transcription on the PC (engine picked per PC; W9XYZ-5: turbo on Intel graphics, final text 2.4 s after unkey for an 8.5 s transmission) | working |
| Words while someone is still talking (base.en, updated each second, replaced by the final text) | working |
| FCC callbook (1.7 M licenses, daily updates) + country lookup for any callsign | working |
| Callsigns spelled phonetically ("Kilo X-ray 7 Fox, Quebec, Zulu" → KX7FQZ; "Fox" for Foxtrot); Whisper's usual mishearings ("Helo", "Sheila", "Gila", "Cilo" for Kilo, "Indy" for India, "Austin" for Oscar, "Vicky" for Victor, "Yanky") count only when the FCC database or roster knows the call | working; a call split between written letters and phonetics ("W9X, Yankee, Zulu…") is not joined yet |
| Net-wide callsign agreement: variants of one station merged by FCC licence, first name, town, earlier check-ins; clipped and unlisted calls found only with a name/town/history; nothing supported = kept, *unverified* | working (`station/consensus.py`, `tools/consensus.py`, `consensus: false`); 11-03 FM net (140 transmissions, FCC on the dev Mac, no history yet): 11 readings moved, 5 calls found in the text, none contradicted by the transcript, the ambiguous ones left as heard. First live night (3 nets): 41 moves, several over-reached (two letters on a name heard in the reply, one name used twice, merging a call heard as its own station); the rules above now keep 25 of them and drop 16 (dry run, same day); clipped calls back under the one-licence rule: 1 of 4 completed (the other 3 have two in-state licences each, left as heard) |
| VHF/UHF callsign distance (Census ZIP centres): clipped calls to the clearly nearest licence, in-range scoring instead of the state, calls beyond 300 km (Settings → VHF/UHF reach) that nothing backs not counted | working (`hamkit/zipgeo.py`); 11-03 nets: every station heard 3+ times was within 50 km, 32 of 33 licences beyond 250 km were heard once (misreadings) |
| **VHF/UHF path analysis** over real terrain (for Einstein to call as a tool when planning a net or Winlink links, never guessing terrain): ground sampled every 100 m along the path (USGS 3DEP, or Open-Meteo's 90 m worldwide data; cached in the callbook folder; no data = an error, never flat ground), k = 4/3 earth, line of sight and Fresnel clearance, the worst obstruction, free-space + knife-edge/Deygout diffraction loss (ITU-R P.526), link budget and fade margin for FM voice / VARA FM / 1200-baud packet, a verdict in plain words; every pair of sites, the best relay site, the mast height that clears the path (`hamkit/pathprofile.py`, `python -m hamkit.pathprofile`) | built + unit-tested on synthetic terrain 2026-11-12 (textbook Fresnel radius and path loss); checked on real terrain with Open-Meteo; USGS answered 0.6–30 s a point that day (some 504s), so a long uncached path takes minutes from it; Einstein uses Open-Meteo when two of the operator's **Sites** are named |
| Local-name fix-ups after transcription (`fixups:` in vocab/local.yaml, learned pairs, the net's own name by sound) | working (`station/fixups.py`); 11-03 net: "Aries" x3, "Windlink" x1 |
| Near-miss callsign correction ('W9XVZ' -> W9XYZ heard in this net, 'K7ABD Springfield' -> K7ABC of Springfield); only when one reading clearly wins, what was heard kept (dotted underline + tooltip), live and accurate text, stations heard and Winlink use the corrected call; 15 min after a net ends it runs once more with the whole net known; uncertain ones show as "WV78? KV7RMV KB7XT" to click; expired licences are not ticked in the Winlink To: list | working (`hamkit/callfix.py`, `callfix: false` turns it off); 3.915 net: 8 corrections, none contradicted, most garbles left as heard |
| QRZ.com online lookups (grid, international names), cached for offline use | working (`hamkit.qrz set-login`) |
| Confirmed / can't-be-confirmed mark on every call (FCC Active, current QRZ.com record, roster); an operator's old call moved to the current one by QRZ alias, within VHF/UHF reach | working (`station/consensus.py` `qrz_answers`, `confirm`); 11-03: 4 old calls moved, 17 calls left counted but unconfirmed, each with its reason |
| Q-code / proword / abbreviation explanations | working (`config/glossary.yaml`) |
| Operator hints: relay, check-in, emergency, formal traffic, exercise, CQ/DX, 10-minute ID | working (`config/procedures.yaml`) |
| Net type recognition (emergency, exercise, ARES/RACES, SKYWARN, NTS, check-in, DX) | working, rules-based |
| Live dashboard in the browser (on the station PC or any PC/phone on the network) | working (`station/`, port 8091) |
| The log by what is happening now: On the air (open) or one line for the net on now / Up next; Completed nets and conversations one collapsed line each under a day heading; Stations heard counts the same calls as the log | working (2026-11-04; checked on desktop + phone widths with the first live night's log) |
| Winlink ICS-309 + ICS-213 into the Winlink Express Outbox, To: = everyone who took part | built; Outbox format matched against Winlink Express 1.8 messages (one and two recipients); first real write to be checked |
| Net schedule with radio, frequency and band; editor in the dashboard (Nets) | working (`data/schedule.json`, seeded from `config/station.yaml`) |
| Repeating nets like Outlook: once, daily, every N weeks on days, monthly by day or nth weekday (1st and 3rd Sunday, last Friday), yearly; ends never / on / after N; skip or move one date; said in plain words with the next 5 dates | working (`station/recur.py`); used for listening, the net running now / next, naming nets in the log and the alert; DST, month ends, 5th weekdays and leap years tested |
| Pre-net alert (5 min before, per net): banner + header strip on every dashboard, Radio is set / Remind me / Skip, chime, title, notification on localhost | working (`station/alerts.py`) |
| Net history: each time a net met, with attendance, net control, transmissions, accurate pass, Winlink sent, minutes; backfilled from the logs | working (`station/history.py`, `data/history.db`, SQLite) |
| Search everything (transmissions, stations, nets, minutes) with filters | working (SQLite FTS5, plain LIKE where FTS5 is missing); 100,000 transmissions: ~0.1 s |
| Net analysis: attendance chart, regulars (stated rule), newcomers, regulars missing, net-control rota, every station's times/first/last/streak | working |
| Minutes drafted by rules (attendance, announcements, schedule, action items, decisions, traffic, urgent), editable with a layer that is never overwritten; Still open; .md / text; in the ICS-213 | working (`station/minutes.py`); on the test nets: 100 % of items found, none wrong; on a held-out net written afterwards: 7 of 9 right, 7 of 8 found before tuning. An LLM tidy-up is stubbed (`minutes: {llm: …}`), not wired yet |
| Urgent board for emergency nets (category, reporter, place, people; Handled) | working |
| Listen only during scheduled nets (auto resume 1 min before, pause 5 min after; optional log at the net's frequency) | working, per radio |
| The end of a net: net control's close heard (wording, roll-call-learned net control, questions/plans/quotes excluded), 2 min tail, pause only a radio the station turned on, final accurate pass at once, minutes, Winlink messages ready; End net by hand; Not closed undoes | working (`station/netclose.py`; built from the 2026-11-03 FM net, where the close had no speaker); not yet seen on a live net |
| Accurate second pass on the home server (large-v3), progress + time left on each net and in the Winlink window | working (`accurate:` in station.yaml) |
| Accurate pass WITH CONTEXT: provisional text per transmission (heard with the net before it), final text for the whole net when it goes quiet (`POST /accurate/context`, `transcribe/context.py`) | working (home server; synthetic FM nets: word errors 53 % → 38 %, callsigns found 11 % → 30 %; real 3.915 net: FCC-valid callsigns 39 → 62; see "How the accurate pass works"); older Mac services fall back to one at a time |
| Home server GPU on demand: Whisper loaded on the first request, its memory released after each one, the model unloaded after 10 idle minutes; a decode stuck 20 min makes `/health` not ok (stations use their own PC) and at 25 min restarts the service (`transcribe/gpu.py`, `/health` shows it) | working (replayed final passes: 4.5 GB flat instead of growing to 20+ GB; idle: 0.77 GB) |
| Accurate pass ON THIS PC when there is no home server (other operators, other networks, offline): OpenVINO large-v3 on the Intel GPU/CPU or faster-whisper on NVIDIA, chosen by an install-time benchmark; held while the live text needs the PC | working on both station PCs (i5-12600H desktop: final text only; Core Ultra laptop: large-v3 on the GPU at 0.34× real time), see "The accurate pass on this PC" |
| Live engine checked while a dashboard is open: a clear transmission read as one word re-checks the engine on a recent good read and reloads it if broken (`station/core.py`) | working (a fake engine in the tests; the failure seen once after Modern Standby) |
| Recordings and net history kept 6 weeks by default (Settings: 1–104 weeks), swept every 6 hours: recordings, day logs, history database rows (then VACUUM), voiceprints, agent drafts, Grok comparisons; stale raw audio, OpenVINO cache over 3 GB, station.log over 10 MB (`station/retention.py`) | working, 2026-11-12 |
| This PC: measured at full speed (screen held on, the processor's speed recorded, a slowed measurement marked), power settings checked with fixes (installer end + Settings), the keep-awake choice asked once at install, a one-time dashboard notice of what changes, a warning when live transcription runs >4× slower than measured, Measure this PC again (`station/pccheck.py`) | working, 2026-11-12 |
| Full speed while transcribing on laptops: your power plan + mode saved, the installer's HAM Sidekick Station plan + Best performance + the screen held on during nets and traffic (+10 min; Settings: or the whole time a radio listens / always / never) or while the accurate pass has work; with every radio paused, only until the accurate pass finishes; all put back after, shown in the header as ⚡ Performance mode / ○ Performance off (and at the next start after a crash; left on the HAM Sidekick power plan with nothing saved, it goes back to Windows' Balanced plan and your power mode) (`station/awake.py`, `keep_awake:`) | working on the test laptop: out of Modern Standby by itself, 6 s → 0.5 s for the same work; plan restored after a hard stop |
| Compiled-model cache for the live engine (`data/ov-cache`, shared with the accurate pass) | working; test laptop: turbo on the GPU 36 s → 16 s to load, small.en on the NPU 555 s → 11 s |
| Over-the-air transcription test with word-error score and history | working |
| Local names (Settings: name, meaning, said as a word/letters, sound-alikes, web site, also-heard phrases, nets by name) repaired in the agreement pass (joined forms, web sites said aloud, a guard for plain words), Local terms in the ICS-213, area packs (export / import file or https / installer `area-pack.json` or `-AreaPack`) | working (`station/localnames.py`), 2026-11-10 |
| Tap-to-correct (✎ Fix, log + minutes transcript; Enter/Esc; ▶ while editing; Undo correction): corrected > accurate > live in search, minutes, attendance, ICS-309/213, Winlink; Learned fixes proposed from repeats, applied only on Accept (`data/fixups_learned.yaml`); accuracy against the corrections per radio/mode/net (`/api/accuracy`, `python -m tools.accuracy`) | working (`station/corrections.py`); not yet used on a live net |
| Who is talking: stated callsign / net control by its words / operator's **Who?** (kept in the log, used by the ICS-309) | working (`station/speaker.py`) |
| Who? suggests the closest voice earlier in the same net (only a clear match; you confirm) | working (`station/voicehint.py`) |
| Who is talking by VOICE (speaker embeddings, to fill in transmissions that name nobody) | measured, **not on**: on the 3.915 MHz LSB net same-voice and different-voice clips overlap almost completely (5 WeSpeaker models; first vs second half of one transmission: EER ~31 %, best match right 8–20 %). FM nets, 2026-11-07 (1,880 transmissions over five days, two receivers, 89 clear self-identifications): within one net the closest voice names the speaker right 72–82 % of the time for 31–62 % of transmissions; across days no better than chance (a station's radio and place change). Below the 90 % needed to show it. Code + `python -m tools.voice_eval` kept |
| Look and feel of the companion EMCOMM forms (slate colours, navy top bar, bold clock); Settings → Display: Automatic / Light / Dark / **Night** (red on black, also the read-out card) and a 24-hour (default) or 12-hour clock; ☾ Night in the top bar | built 2026-11-12, checked in Chromium, Firefox and WebKit (Safari), laptop and phone |
| Top bar status in plain words: ● Live text, ● Home server / Accurate on this PC / Home server offline (model names in the tooltip) | built 2026-11-12 |
| Home server comes and goes: checked every minute while idle; lost mid-net → the rest moves to this PC (or waits) at once, a provisional request gives up after 2 min; back → what waited goes at once | built 2026-11-12 (`station/accurate.py`, tests) |
| Winlink messages: the Outbox button is grey with **🔒 Close Winlink Express first** while Express is open, green **✓ Put in Winlink Express Outbox** with a "ready" band once it is closed | built 2026-11-12 |
| Live engine stuck on the same words (2026-11-11 on a laptop station: one sentence or "The.9.9.9" for ~4 h): checked on **every** transmission (no dashboard needed, at most once a minute); repeated / looped / digit-run output is suspect and never the reference; a fresh graphics engine that is stuck too → the live text moves to the CPU and the top bar says **● Live text on CPU** | built 2026-11-12 (`station/core.py`) |
| Einstein's turn, from the 11-12 review of real nets: who net control called is read around the call ("Any station holding traffic, traffic only. Check in now.", maritime-only calls, "Before I start taking check-ins…", a bare "Please call now." whose start was lost); roll calls by place answered only for **your region** (Settings → Einstein & AI → Station agent); net control's "W9XYZ, thank you, you're in the log" = checked in, not a question; "break break" / emergency traffic silences it on every net; a net can be set to **never check in**. Replayed on 4 real net days: 11 wrong invitations stopped, none lost | built 2026-11-12 (`tests/test_sidekick_turns.py`) |
| Einstein's card: **YOUR TURN** chip (Check-ins open to you / CALLED / Checked in ✓ time / Listening: why), **I checked in myself**, **Mute for this net**, the last draft that would have spoken stays in view, silent drafts counted | built 2026-11-12 |
| Einstein with **no xAI key** or **no internet**: says on its card that it drafts with its offline rules (check in when invited, acknowledge a call; questions wait for the operator), never waits on the network, tries xAI again by itself; **▶ Hear it** uses this computer's own voice | built 2026-11-12, tested both ways |
| Roll calls by place: the US state names are downloaded once from the US Census list (`hamkit/places.py`, 2 KB, into the callbook folder; the installer and the station fetch it), none are in the code; without it the call's shape is used | built 2026-11-12 |
| Urgent board reads **fire** by its grammar: a fire tower, fire seat or fire transducer (fire + a noun) is a thing, "fire it up" is the verb, and a report must be about the word itself ("there's a fire", "fire spreading", "fire on Elm"), not anywhere in the sentence. Replay of 9,475 real transmissions: 8 false alerts gone, no real report lost | fixed 2026-11-12 |
| "This PC is transcribing slowly" is judged on clips of 8 s or more only: a GPU engine costs about 2 s a clip whatever its length, so short clips (an "Over.") looked slow. A day of real traffic: 8 false notices → 0; a PC really 5× slower is still caught | fixed 2026-11-12 |
| **Einstein card**: a two-sided reference card for setting up Einstein and reading it on a net (`station/static/sidekick_card.html`, `/help/sidekick`, PDF in `docs/`) | built 2026-11-12 |
| **Einstein's knowledge library** (`station/knowledge.py`): material Einstein answers questions and gives prepared talks from, with its sources — this station's own manual, README, technical notes and both cards (re-read when they change), plus the operator's files (.md .txt .html .pdf .docx .csv) in `data\knowledge\`, short notes ("Our EOC's Winlink gateways") and web pages fetched once from a URL; searched by SQLite FTS5 (bm25), the question cleaned of spoken filler with ham abbreviations kept (EOC, ARES, VARA, CW, HF…); 20 MB a file, 200 MB in all; a file it cannot read is listed with why | built 2026-11-12 (`tests/test_knowledge.py`); Einstein reads it for answers that think, the chat and talks; dashboard: Einstein → Chat & prepared… → Library |
| **Net board** per radio (a tab above the log): who is in (numbered), **heard once** marked, **Ask again**, traffic, heard but not checked in, regulars not heard yet, net control's 10-minute ID timer; refreshed after each transmission | built 2026-11-12 (`History.board`, `tests/test_review_board.py`) |
| **Review the check-ins** after a net (✓ / ✎ right call / ✗, ▶ where it was heard): fixes the attendance, the minutes, the ICS-309 and Winlink messages; calls heard once show as **(?)** until reviewed; each mark is logged to `data/review_log.jsonl` as the human truth for call accuracy | built 2026-11-12 |
| Phones: the radio column scrolls as a whole when the notices and Einstein's card are taller than the screen (the tabs under them were out of reach) | fixed 2026-11-12 |
| Read-out end to end with the forms project's real EOC server (`tests/test_forms_e2e.py`, `EMCOMM_FORMS_REPO=…`); the two copies of the contract checked identical | tested 2026-11-12 against forms 2026-11-12.3 |

## License

MIT — see [LICENSE](LICENSE). Use it, change it and share it, for your club, ARES group or EOC.

## About

HAM Sidekick Station was created as a volunteer contribution to the amateur radio and EMCOMM (emergency communications) community, in the same family as the [Church of Jesus Christ EMCOMM forms](https://github.com/travislhilton/church-emcomm-wnlk-forms). It is offered freely to any club, ARES group or EOC that can use it. It is an independent project, not an official product of any church, club or agency.
