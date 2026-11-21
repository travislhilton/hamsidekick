# HSK1: keyboard chat and file transfer over VARA

HAM Sidekick Station chats and sends files over a VARA HF or VARA FM link (`station/vara.py`). This is the framing
it puts on VARA's data port, published so any program can talk to it. It is this project's own protocol: it is not
VarAC's (whose protocol is unpublished) and makes no claim to work with it.

## The modem

The station drives VARA over its TCP interface: the command port (8300 by default; ASCII lines ending in CR) and the
data port (8301; the connected session's bytes). On start it sends `MYCALL <call>`, `LISTEN OFF`, `COMPRESSION TEXT`
and, on VARA HF, `P2P SESSION` and `CWID ON`. Listening for calls is `CHAT ON` (VARA's keyboard-chat timing, which
includes `LISTEN ON`); `CONNECT <me> <them>` (VARA FM: `... via <digi> <digi>`), `DISCONNECT`, `ABORT` and
`CQFRAME <me> <bw>` (VARA FM: `CQFRAME <me> [digis]`) do what they say. It never sends an `ENCRYPT` command: amateur
radio messages may not be obscured (FCC Part 97.113).

## The framing

Everything is bytes on the data port; a header line ends in LF (`\n`), its fields are separated by single spaces.
The bytes may arrive in any size of piece: a receiver buffers until a header line, or a body, is complete.

| From either side | Meaning |
|---|---|
| `HSK1 <call>\n` | Sent once by each side right after `CONNECTED`: "I speak HSK1". |
| `MSG <seq> <len>\n` then `<len>` bytes | A chat message: UTF-8 text, line breaks as LF, at most 4000 characters. |
| `FILE <seq> <name> <size> <sha256>\n` then `<size>` bytes | A file. `<name>` is percent-encoded (no spaces), `<sha256>` the 64-hex-digit SHA-256 of the bytes. |
| `OFFER <seq> <name> <size>\n` | A notice sent just before a FILE with the same `<seq>`: the receiver shows the name, size and progress at once (VARA hands a file over a block at a time, so its FILE header can arrive a minute late). The FILE follows when the sender's modem has sent the notice. A program that does not know OFFER ignores the line. |
| `TESTING <seq> <seconds>\n` | The same kind of notice before a link test. |
| `RXCANCEL <name> <done> <size>\n` | "My operator stopped your file `<name>` after `<done>` of `<size>` bytes." Sent over a new short link after the receiver dropped the link (nothing can be sent back while a file is flowing: VARA does not turn the link around). The sender marks that file "cancelled by the operator at <call>", so it is not taken for a link failure. |
| `ACK <seq>\n` | The receiver's answer to a FILE: received whole, the SHA-256 matches, saved. |
| `NAK <seq> <reason>\n` | The receiver's answer to a FILE: not saved (`checksum mismatch`, `too large (...)`, ...). |
| `TEST <seq> <len>\n` then `<len>` bytes | Link test data: random bytes, thrown away by the receiver (never saved or shown). Sent in several frames with one `<seq>`. |
| `TESTEND <seq>\n` | The end of a link test. |
| `TESTED <seq> <bytes> <ms>\n` | The receiver's answer to TESTEND: the bytes it counted (headers included) and the milliseconds from the first TEST frame. |

**Digipeaters (VARA FM).** `CONNECT <me> <them> via <digi1> [<digi2>]` and `CQFRAME <me> <digi1> [<digi2>]` relay
a link or an announcement through at most two VARA FM digipeaters (a VARA FM whose Digipeater call is set in its
own VARA Setup). A CQ frame heard through digipeaters is reported with them after the call; the station keeps that
path, reversed, as the way back. HSK1 itself is unchanged over a relayed link.

**Capabilities.** The handshake may carry words after the call, each starting with `+`: `HSK1 <call> +TEST` says
"I understand the link test". A link test is sent only to a station that said `+TEST`; a station that did not is
never sent a TEST frame. Unknown `+` words are ignored.

**The link test** (the operator presses **Test link speed**; it is never sent by itself). VARA starts a link at a
low speed level and steps up as data flows, so a file's speed depends on its size. The sender switches to
`COMPRESSION FILES`, feeds random bytes for the chosen time (15 to 180 s), keeping about 15 s of data ahead of the
modem (1 to 16 KB), and notes from VARA's `BUFFER` lines how many bytes the other modem has taken, second by second.
When the time is up it lets the modem empty, sends `TESTEND`, and switches back to `COMPRESSION TEXT` on `TESTED`.
From that curve the station works out how long a file of a given size takes: up to the size the test reached, the
time is read off the curve; beyond it, the rest goes at the speed of the test's last third. VARA's own `BITRATE`
lines (speed level and bit rate) and `SN` are recorded beside it.

**AI stations (Einstein).** A station's AI assistant answers at a call of its own (the operator's base call with
another SSID; VARA's `MYCALL` takes several calls, so both share one modem). Its handshake says what it is:
`HSK1 W9XYZ-15 +TEST +AI +OF=W9XYZ-7 +NAME=Einstein +NONCE=<16 hex>`, and while it answers, the operator's own call
says where to find it: `HSK1 W9XYZ-7 +TEST +AI=W9XYZ-15`. Other stations list the AI station under its operator's.
Two more header lines (ignored by a program that does not know them):

| From | Line | Meaning |
|---|---|---|
| the asker | `AUTH <32 hex>\n` | "I am this station's operator": the first 32 hex digits of HMAC-SHA256(owner key, `<NONCE>:<my call>`), sent by a station with the same base call that holds the same owner key. It proves the key without saying it and hides nothing (Part 97: authentication, not encryption). The AI station then also takes STATUS, MESSAGES, PAUSE and RESUME. |
| the AI station | `WORKING <seconds>\n` | "Working on your question": the asker keeps the link open (up to about 2½ minutes) for the answer instead of letting it go after its usual quiet time. |

An AI station only answers: it never opens a link. An answer not ready when the link closes is kept (6 hours) and
sent on the asker's next link to it. Its first message in a session says it is an automated assistant and names the
control operator; it gives its call every 10 minutes. See [EINSTEIN.md](EINSTEIN.md).

* `<seq>` counts up from 1 per sender per session; an ACK or NAK names the FILE it answers.
* A FILE larger than the receiver takes (this station: 5 MB) is still read to its end (so the stream stays in step)
  and answered with NAK.
* Unknown header lines are ignored.
* The sender switches the modem to `COMPRESSION FILES` before a FILE and back to `COMPRESSION TEXT` once every file
  it sent has its ACK or NAK.

## A plain VARA terminal

If the other side's first bytes are not `HSK1 `, it is treated as a plain terminal: what it sends is shown as chat,
one line at a time (CR, LF or CRLF), and chat sent to it goes as plain text lines ending in CRLF. Files are not
offered to it.

## What the receiving station does with a file

It is saved in `data/vara/inbox/` as `<date-time>-<sender>-<name>`: the name stripped of folders and of anything but
letters, digits, `.`, `_` and `-`; never hidden; a program or script kind (`.exe`, `.bat`, `.ps1`, `.js`, `.msi`,
...) gets `.blocked` added so a double-click cannot run it. Every message and file, both ways, is recorded in
`data/vara/<YYYY-MM>.jsonl`.

## Transmitting

Every transmission the station can cause over VARA needs the station's permission at that moment (the operator
present, the radio's transmit switch on): calling, a CQ, listening (VARA answers calls by itself while listening),
every message or file, and the protocol's own HSK1, ACK and NAK. If permission goes away mid-session, the station
aborts the link rather than send. There is no automatic reply, relay or forwarding; the channel's keep-alives (below)
are sent only while the operator is at the station. When the station (not
VARA) keys the radio, it follows VARA's `PTT ON` / `PTT OFF` and aborts the link if the transmitter stays on, or a
file waits for its receipt, longer than 10 minutes.

VARA serves one program at a time: while Winlink Express is open, the station does not connect to VARA, and it lets
go of VARA when Winlink Express opens while no session is up.

## The channel (who is on the frequency)

VARA links one station at a time, and the only frame it sends without a link is the **CQ frame** (`CQFRAME`, which
carries the callsign and nothing else). The station's channel view (`station/varachan.py`) is built on those two
facts; it adds nothing to the framing above.

* **Joining** sends one CQ frame (the announcement) and turns listening on; while joined, another CQ frame goes every
  *n* minutes (default 10 on VARA FM, 15 on VARA HF; 5 to 60): the keep-alive. Only while the operator is at the
  station with the radio's transmit switch on; it waits for the frequency to be clear and for no link to be up.
* **Presence**: every CQ frame heard, and every link with a station, marks it *here*. Not heard for one interval plus
  3 minutes: *quiet* (grey). After three intervals: *gone*. A station leaving sends nothing (no frame says so), so it
  greys out.
* **Messages** to a station are queued. When no link is up and the frequency is clear (VARA's `BUSY OFF`), the station
  links to the oldest waiting station, sends what waits for it as `MSG` / `FILE` frames, and disconnects after 20 s
  (VARA HF 40 s) with nothing moving, or 5 s when other stations are waiting, never before VARA's buffer is empty. A
  message is *sent* when written and *delivered* when VARA reports `BUFFER 0` (its ARQ has every byte on the other
  modem); a file is delivered on its `ACK`. A link the other station opened is left for it to close, and what waits
  for that station goes out on it. A call not answered is tried 3 times, 30 s or more apart.
* **Several stations "at once"** = one link after another: the same message is queued for each.
