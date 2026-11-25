# Einstein on the air

Einstein is the station's AI assistant. Over VARA it answers other amateurs at **a call of its own**: your call
with another SSID, e.g. `W9XYZ-15` beside your `W9XYZ-7`. Other stations running HAM Sidekick Station list it
under your call, with a 🤖. A plain VARA terminal can talk to it too.

## Switching it on

1. Settings → **Einstein & AI**: set the **xAI key** and your **license class**.
2. Set up the data radio's VARA modem for chat (VARA chat and files → Modem setup).
3. In the radio's VARA panel, **🤖 Einstein on the air** → **Switch on**. Its call is suggested (SSID 15, 14,
   13 … whichever is free); change it in the same bar.

It switches on only with the xAI key and the internet, and only from a dashboard with transmitting allowed (the
radio's Transmit switch on, your license class with data privileges at its frequency). With no internet it stops
answering (its call comes off the modem) and comes back by itself when the internet does.

## What other stations can ask

Anything: radio, emergency communications, technical questions, general knowledge. Type **HELP** to it for its
list. Files arrive after its answer and open with **View** (a form as the form, a CHIRP file as a table):

| Ask for | It sends |
|---|---|
| "Local EMCOMM CHIRP file (2m/70cm/ad hoc)" | one CHIRP file for a handheld: per band (2 m, then 70 cm) the FM voice repeaters, then simplex, from the local plans you chose (ARES, RACES, ICS-205, club) and the plan channels you kept, then the national calling channel, then your reserved ad hoc channels. Never packet, APRS, Winlink gateways, D-Star / DMR or weak-signal channels |
| "CHIRP file of the 2 m simplex channels for a Baofeng" | a CHIRP memory CSV: your radio list, the band plan's channels, your ad hoc channels, or channels the asker lists |
| "The band plan for 70 cm for my license" | the area band plan, with the asker's privileges (their class from the FCC database) |
| "Weather for Springfield, IL as an ICS-213" | an ICS-213 General Message from the US National Weather Service (Open-Meteo outside the US), with active alerts; plus Winlink Express form data when Express is on the station PC |
| "HF band conditions" | solar flux, K index and NOAA scales from NOAA SWPC, in words, optionally as an ICS-213 |
| "An ICS-205 of the ad hoc channels for the drill" | an ICS-205 Incident Radio Communications Plan |
| "An ICS-309 log of this session" | an ICS-309 Communications Log of the conversation |
| "When are this station's nets?" | the nets on your schedule and when they meet next |
| "Your net schedule as a calendar file" | two files: a calendar (.ics, each meeting of the next 8 weeks: any phone or computer calendar opens it) and a HAM Sidekick net file (.hsnets: their station shows **📅 Add N nets…**, previews them and adds them like Share settings: never deletes, waits in Nets for a radio). Only the nets' name, frequency, offset, tone, times, repeat rule, cancellations and net control travel |
| "Look up K7ABC" | the public FCC (or country) entry: name, class, city, state (never a street address) |
| "Leave a message for the operator: …" | a note in **✉ Notes** on your VARA panel (the only message it takes) |
| library questions | only when you tick "Einstein may search this station's library" |

## Watching it work

On the station running Einstein, a question shows under the 🤖 bar the moment it comes in: who asked, what, and
Einstein's step as it goes (reading the question, thinking, the tool it is using, writing, sending the answer and its
files) with a running clock; then the outcome and how long it took, or why it turned the question away. The last
questions fold below. The asking station sees "… is working on your question…" in the chat.

## Part 97, in code

The model cannot talk its way past these: the station checks them before anything is sent.

* **Identification and disclosure.** Its first message in every session says it is an automated AI assistant at
  your station and names you as licensee and control operator; its call goes out every 10 minutes (97.119).
* **Automatic control only where allowed** (97.109(d), 97.221). With you at a dashboard (here, or at another of
  your stations: see below) both calls answer. With you away, only Einstein's call answers, and only:
  * on 6 m and shorter where your class has data privileges: answers, and announces itself with your keep-alives;
  * in the HF automatic-control data segments of 97.221(b): answers and announces;
  * elsewhere on HF: only answering a station that calls it, on VARA HF 500 Hz (97.221(c)); never on 60 m. It
    does not announce there.

  It never opens a link: what it sends goes on the link the other station opened. An answer not ready when that
  link closes waits (6 hours) for that station's next link.
* **Content** (97.113): no indecent words, codes or ciphers, business (buying, selling, payment), music; it never
  claims to be a person.
* **No third-party traffic** (97.115): it never relays a message; it only takes notes for you.
* **Licensed amateurs only**: US calls are checked in the FCC database on the station, others by their prefix.
* **Emergencies**: anyone in danger is told at once to call 911 or a local emergency net, and you get an alert.
* **Limits**: 20 questions an hour from one station, 8 files an hour, 300 questions a day, 64 KB a file.
* Everything it hears and sends is in the VARA panel's conversation and in `data/einstein/` (monthly logs).

## You, at another of your stations

**Talking to it over the air.** From W9XYZ-8, link to W9XYZ-7's Einstein (`W9XYZ-15`) like any station. With the
same **owner key** on both stations (Settings → Einstein & AI → Einstein on the air: **Make a new key** on one,
type it on the others), the asking station proves it holds the key (an HMAC in the clear, like Winlink's secure
login; the key never goes on the air) and you may also send:

| Command | Does |
|---|---|
| `STATUS` | its state, frequency, questions in 24 h, unread notes, who is linked |
| `MESSAGES` | the unread notes stations left for you |
| `PAUSE` | stop answering (when this link closes) |
| `RESUME` | answer again |

**Being its control operator from here** (remote control, 97.213). Settings → Einstein & AI → **My other
stations**: their dashboard addresses (LAN or Tailscale, e.g. `http://192.168.1.20:8091`). Then **My stations**
(top of the dashboard) shows each one: its radios, frequencies, Transmit switches, VARA links, Einstein. Tick
**Control from here** and, while you use this dashboard, that station counts its control operator as present:
its VARA chat, its voice Send (Einstein speaking on a voice net needs a present control operator: there is no
automatic control of voice, 97.109(d)) and both of its calls work as if you were at it. Stop using this dashboard
for 3 minutes and it stops transmitting by itself. **⏹ Stop it transmitting** drops any transmission and VARA link
there at once. The tick lives in this browser only, never on the server: it is you, at this keyboard. You must be
able to monitor that station's transmissions: for voice, that means its audio too.

## Where it lives

`station/einstein.py` (the rules, the tools, the session), `station/forms.py` (ICS-213 / 205 / 309 pages and
Winlink Express form data), `station/wx.py` (weather, space weather), `station/remote.py` (my other stations),
`station/vara.py` / `varalink.py` / `varachan.py` (several calls on one modem, who may transmit for which call, the
AI rows and the asker's side). Protocol additions: [VARA.md](VARA.md). Tests: `tests/test_einstein.py`.
