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
| `ACK <seq>\n` | The receiver's answer to a FILE: received whole, the SHA-256 matches, saved. |
| `NAK <seq> <reason>\n` | The receiver's answer to a FILE: not saved (`checksum mismatch`, `too large (...)`, ...). |

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
