# Forex Arbitrage Subscriber

A Python project implementing a distributed **Forex Quote Subscriber** that detects currency arbitrage opportunities using the **Bellman-Ford algorithm**.

## Overview

This project simulates a trading system's component, the **Subscriber** (`subscriber.py`), which connects to a **Forex Provider** (`forex_provider.py`). The Subscriber continuously listens for real-time currency quotes via UDP. Upon receiving quotes, it models the exchange rates as a graph, where currencies are nodes and the **negative logarithm** of the exchange rates are edge weights. The **Bellman-Ford algorithm** is then used to detect **negative cycles**, which correspond to profitable **arbitrage opportunities**. The system is designed for concurrency, with separate threads for listening to quotes and renewing the subscription.



---

## Architecture

The system consists of three main Python files:

1.  **Subscriber (`subscriber.py`)**: The core logic. Listens for quotes, builds the exchange rate graph, runs Bellman-Ford, and logs arbitrage opportunities.
2.  **Forex Provider (`forex_provider.py`)**: A simulation of a real-world forex provider that sends UDP quote messages to subscribers and handles subscription requests.
3.  **BellmanFord (`bellman_ford.py`)**: A standalone implementation of the Bellman-Ford algorithm for shortest path and negative cycle detection.

### Supporting Files

* **`fxp_bytes_subscriber.py`**: Contains utility functions for **unmarshaling** the byte-formatted quote messages and **deserializing** data received from the Provider.
* **`fxp_bytes.py`**: Contains utility functions for **marshaling** quote messages and **serializing** addresses for the Provider.

### Message Types

The communication uses standard UDP sockets, but the data flow follows a subscription model:

-   **`SUBSCRIBE`**: Sent from the Subscriber to the Provider to initiate and periodically renew the quote stream. The message contains the Subscriber's listening address.
-   **`QUOTE`**: Sent from the Provider to the Subscriber, containing byte-formatted exchange rate data.

---

## Key Concepts

* **Arbitrage:** A strategy where a trader simultaneously buys and sells an asset in different markets to profit from a tiny difference in their prices. In forex, this involves a cycle of three or more currency exchanges that results in a net gain (e.g., USD → EUR → GBP → USD).
* **Graph Model:** Exchange rates are mapped to a graph where:
    * **Vertices** are **currencies** (e.g., USD, EUR).
    * **Edge Weights** are the **negative logarithm of the exchange rate**. This transformation converts a maximization problem (maximizing profit) into a minimization problem (finding the shortest path/negative cycle).
* **Bellman-Ford Algorithm:** An algorithm used to find the shortest paths in a graph. A **negative cycle** (a path whose total weight is less than zero) in the currency graph indicates a profitable arbitrage opportunity.

---

## Usage

### Start the Forex Provider

The Provider will simulate sending quotes and handle subscription requests.

```bash
python forex_provider.py
