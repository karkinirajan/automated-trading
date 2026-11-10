# 2. The trading rules and the look-ahead guarantee

The agent is a language model calling `buy` and `sell`, so every argument it sends is untrusted, and the account has to hold up against a model that is wrong, creative or simply careless.

## What an order must satisfy

`tools/trading.py` refuses an order, and changes nothing, when:

| Condition | Why it matters |
| --- | --- |
| `amount` is not an integer, or is a `bool` | A fraction of a share is not a thing in this simulation; `True` is not 1. |
| `amount` is below 1 or above 1,000,000,000 | **A negative "purchase" used to add cash and subtract shares**, and a zero or negative sale used to buy shares for free. |
| there is no usable price (missing, zero, negative, NaN, infinite) | A symbol with no opening price that day cannot be traded. |
| a purchase costs more than the cash held (beyond a 1e-9 rounding tolerance) | Cash never goes negative. |
| a sale is for more shares than are held, or of a symbol not held | No short selling. |
| the symbol has no position entry or no price for the day | Unknown symbols are refused with `Symbol X not found!`. |

A refused order returns `{"error": ..., "symbol": ..., "date": ...}` to the model (a hint for its next step) and the position file is untouched. Orders execute at **today's opening price**.

### One lock around the whole order

`execute_trade` reads the latest position, checks, and appends the new position inside a single exclusive file lock per agent. Without it, two orders arriving together both read the same cash and both succeed (twelve concurrent one-share purchases at 100 against 1,000 in cash now succeed exactly ten times; the test widens the window on purpose, so that removing the lock fails it). The lock uses `fcntl`, so **trading needs Linux or macOS**; on Windows it refuses to run rather than pretend.

## What the model may see

The simulation clock is `TODAY_DATE` in the agent's settings file.

| Asked for | Daily run | Hourly run |
| --- | --- | --- |
| an earlier day / hour | full open, high, low, close, volume | full |
| the current day / hour | **the open only**; high, low, close and volume are replaced with a note | open only |
| a later day / hour | refused | refused |
| anything, when no clock is set | refused (look-ahead cannot be ruled out) | refused |

A daily price for the current day stays open-only even in an hourly run (the day is not over). When a date is missing the error lists "sample available dates", and only dates the agent may see.

`data/merged.jsonl` itself holds the whole future. That is safe only because the agent has no file tools: prices reach it through `get_price_local`, `merge_jsonl.py` strips the latest bar down to its open, and the system prompt contains yesterday's closes and today's opens only.

## Web search

`get_information` searches with Jina and reads **one** page. Results are filtered by the date Jina reports before any page is read:

* a result dated at or after the simulated moment is dropped (an instant exactly equal to it too);
* a result with **no date, or a date that cannot be read, is dropped**. It used to be kept, which let undated pages from after the simulated date through;
* relative dates ("4 hours ago") are measured from the real current time, since that is when the page was fetched, so on an old replay they count as recent and are dropped;
* with no simulated date set, results are not filtered.

## What this does not guarantee

* A model's **training data** already contains the period it is replaying; no tool can make it forget. A good replay result is weak evidence.
* A page whose publication date Jina reports wrongly can still be shown, and a page published earlier may have been edited later.
* The tool servers have no authentication and listen on `127.0.0.1` unless `MCP_HOST` says otherwise. Anything on the machine that can reach the port can place orders for any agent that has a folder: do not expose them.
