import math
import time
from datetime import datetime, timedelta, timezone
import socket
import threading
import fxp_bytes_subscriber
from bellman_ford import BellmanFord

MAX_BUFFER_SIZE = 1024
QUOTE_EXPIRATION_TIME = 0.1
SUBSCRIPTION_EXPIRATION_TIME = 10 * 60
QUOTE_STALE_TIMEOUT = 1.5 
ARBITRAGE_START_AMOUNT = 100


class Subscriber(object):
    def __init__(self, forex_provider_address):
        """Initializes the subscriber with connection addresses and data structures."""
        self.listener_address = (socket.gethostbyname(socket.gethostname()), 42555)
        self.forex_provider_address = forex_provider_address
        self.rate_graph = {} # Stores currency pairs and their negative log rates for Bellman-Ford.
        self.quote_timestamps = {} # Stores timestamps for quotes to check for staleness.

    def add_to_graph(self, currencies, quote_data):
        """Updates the rate_graph with a new quote and its reciprocal, using negative log rates."""
        # The edges are the negative log of the current exchange rate.
        forward_rate_neg_log = -1 * math.log(quote_data["price"])
        quote_timestamp = quote_data["timestamp"]
        
        base_currency = currencies[0]
        quote_currency = currencies[1]
        
        # This adds the base_currency -> quote_currency edge.
        if base_currency not in self.rate_graph:
            self.rate_graph[base_currency] = {}
        self.rate_graph[base_currency][quote_currency] = forward_rate_neg_log
        self.quote_timestamps[(base_currency, quote_currency)] = quote_timestamp

        # An edge for the reciprocal rate (quote_currency -> base_currency) must also be added.
        reciprocal_rate_neg_log = -1 * forward_rate_neg_log
        if quote_currency not in self.rate_graph:
            self.rate_graph[quote_currency] = {}
        self.rate_graph[quote_currency][base_currency] = reciprocal_rate_neg_log
        self.quote_timestamps[(quote_currency, base_currency)] = quote_timestamp

    def cleanup_graph(self):
        """Removes stale quotes (edges) from the rate_graph that have exceeded the QUOTE_STALE_TIMEOUT."""
        # A published quote is assumed to remain in force for QUOTE_STALE_TIMEOUT.
        stale_cutoff_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=QUOTE_STALE_TIMEOUT)

        # This collects edges to delete.
        edges_to_delete = [
            (source_curr, target_curr) for (source_curr, target_curr), timestamp in self.quote_timestamps.items()
            if timestamp <= stale_cutoff_time
        ]

        for (source_curr, target_curr) in edges_to_delete:
            # Check for the forward rate.
            if source_curr in self.rate_graph and target_curr in self.rate_graph[source_curr]:
                del self.rate_graph[source_curr][target_curr]
                self.log("CLEANUP", f"Removing stale quote for {source_curr, target_curr}")
            
            # The reciprocal edge is automatically removed here since both (u, v) and (v, u) are checked and deleted if found in timestamps.
            if target_curr in self.rate_graph and source_curr in self.rate_graph[target_curr]:
                del self.rate_graph[target_curr][source_curr]

            # Both timestamp entries must be removed.
            if (source_curr, target_curr) in self.quote_timestamps:
                del self.quote_timestamps[(source_curr, target_curr)]
            
            # The reciprocal timestamp key might be (v, u).
            if (target_curr, source_curr) in self.quote_timestamps:
                del self.quote_timestamps[(target_curr, source_curr)]


    def print_arbitrage(self, predecessor_map, cycle_start_currency, initial_trade_amount=ARBITRAGE_START_AMOUNT):
        """
        Reconstructs and logs the sequence of trades for an arbitrage opportunity (negative cycle).

        :param predecessor_map: the dictionary of predecessor nodes (prev) from Bellman-Ford.
        :param cycle_start_currency: the currency node where the negative cycle was detected.
        :param initial_trade_amount: the initial amount of money to exchange.
        """
        if cycle_start_currency not in predecessor_map or predecessor_map[cycle_start_currency] is None:
            self.log("WARNING", f"Cannot reconstruct path starting from {cycle_start_currency}")
            return
        
        # Iterate through predecessor_map from the end to the beginning to reconstruct the cycle path.
        cycle_steps = [cycle_start_currency]
        current_step = predecessor_map[cycle_start_currency]
        
        visited_nodes = set()
        # Loop until the cycle closes.
        while current_step is not None and current_step not in visited_nodes:
            cycle_steps.append(current_step)
            visited_nodes.add(current_step)
            current_step = predecessor_map.get(current_step, None)
            # This stops the loop if we looped back to the origin.
            if current_step == cycle_start_currency:
                cycle_steps.append(current_step)
                break

        cycle_steps.reverse()
        
        # Ensure a valid cycle of at least two steps (e.g., A -> B -> A).
        if len(cycle_steps) < 2 or cycle_steps[0] != cycle_steps[-1]:
            return

        # Log the beginning of the arbitrage sequence.
        self.log("ARBITRAGE", "Cycle found.")
        
        # Log the starting amount.
        self.log("ARBITRAGE", f"Start with {cycle_start_currency} {initial_trade_amount}")
        
        current_amount = initial_trade_amount
        previous_currency = cycle_start_currency
        
        # Iterate up to the second to last step since the last step connects back to the start.
        for i in range(1, len(cycle_steps)):
            next_currency = cycle_steps[i]
            # Handle the final step connecting back to the start.
            if i == len(cycle_steps) - 1:
                next_currency = cycle_steps[0] 

            # Convert the negative log back into the exchange rate (price) and update the value.
            if previous_currency not in self.rate_graph or next_currency not in self.rate_graph[previous_currency]:
                self.log("WARNING", f"Edge {previous_currency}->{next_currency} missing during print_arbitrage.")
                return 

            exchange_rate = math.exp(-1 * self.rate_graph[previous_currency][next_currency])
            current_amount *= exchange_rate
            
            self.log("ARBITRAGE", f"Exchange {previous_currency} for {next_currency} at {exchange_rate} --> {next_currency} {current_amount}")
            previous_currency = next_currency

    def listen(self):
        """
        Binds the socket to listen for incoming forex quotes, processes them, and runs the Bellman-Ford algorithm
        to detect and report arbitrage opportunities.
        """
        self.log("SYSTEM", f"Listening on {self.listener_address}")
        # Used to check for out-of-sequence quotes (latest quote timestamp seen across all markets).
        last_processed_time = datetime.now() 

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as listener_socket:
            listener_socket.bind(self.listener_address)
            while True:
                try:
                    byte_message, _ = listener_socket.recvfrom(MAX_BUFFER_SIZE)
                    unmarshaled_quotes = fxp_bytes_subscriber.unmarshal_message(byte_message)

                    for quote_data in unmarshaled_quotes:
                        quote_timestamp = quote_data["timestamp"]
                        time_difference = (last_processed_time - quote_timestamp).total_seconds()
                        
                        currency_pair = quote_data["cross"].split("/")
                        price_string = f"{currency_pair[0]} {currency_pair[1]} {quote_data['price']}"

                        # Ignore any quotes with timestamps before the latest one seen for that market (within tolerance).
                        if time_difference < QUOTE_EXPIRATION_TIME:
                            self.log("QUOTE", f"{price_string}")
                            self.add_to_graph(currency_pair, quote_data)
                            last_processed_time = quote_data["timestamp"]
                        else:
                            self.log("QUOTE", f"{price_string}")
                            self.log("WARNING", "Ignoring out-of-sequence message")

                    self.cleanup_graph()

                    # Run Bellman-Ford to check for negative cycles.
                    if self.rate_graph:
                        bellman_ford = BellmanFord(self.rate_graph)
                        # Start node is arbitrary since we only care about cycles.
                        distances, predecessors, negative_edge = bellman_ford.shortest_paths('USD', 1e-12)
                        
                        # A negative_edge indicates a negative cycle (arbitrage).
                        if negative_edge is not None:
                            
                            # Patch the predecessor dictionary to start cycle reconstruction.
                            u_node, v_node = negative_edge
                            if predecessors.get(v_node) is None:
                                predecessors[v_node] = u_node
                            
                            # Start reconstruction at the node where the negative edge was found.
                            cycle_detection_node = negative_edge[0]

                            # Walk back |V| times to ensure the start node is inside the cycle.
                            num_nodes = len(self.rate_graph)
                            for _ in range(num_nodes):
                                cycle_detection_node = predecessors.get(cycle_detection_node, None)
                                if cycle_detection_node is None:
                                    break

                            # Report any arbitrage opportunities.
                            if cycle_detection_node is not None:
                                self.print_arbitrage(predecessors, cycle_detection_node)
                            else:
                                self.log("WARNING", "Could not reconstruct cycle (no valid predecessor chain)")

                except Exception as e:
                    import traceback
                    self.log("ERROR", f"Listener error: {e}")
                    self.log("ERROR", traceback.format_exc())

    def subscribe(self):
        """
        Periodically sends a SUBSCRIBE message to the forex provider to renew the subscription.
        """
        while True:
            try:
                self.log("SUBSCRIBE", f"Sending SUBSCRIBE to {self.forex_provider_address}")
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as subscriber_socket:
                    # fxp_bytes_subscriber.serialize_address returns the byte string of the address tuple
                    serialized_listener_address = fxp_bytes_subscriber.serialize_address(self.listener_address)
                    subscriber_socket.sendto(serialized_listener_address, self.forex_provider_address)
                
                # Wait before renewing the subscription.
                time.sleep(SUBSCRIPTION_EXPIRATION_TIME)
            except Exception as e:
                self.log("ERROR", f"Subscription error: {e}")
                time.sleep(5)

    def run(self):
        """
        Starts the listener and subscriber threads to operate concurrently.
        """
        listener_thread = threading.Thread(target=self.listen, daemon=True)
        subscribe_thread = threading.Thread(target=self.subscribe, daemon=True)

        listener_thread.start()
        subscribe_thread.start()

        listener_thread.join()
        subscribe_thread.join()

    def log(self, category, message):
        """Prints a log message with a timestamp and category."""
        print(f"[{datetime.now()}] [{category}]: {message}")

if __name__ == "__main__":
    # Main execution block: defines the provider address and starts the Subscriber instance.
    forex_provider_address = ("localhost", 50403)
    subscriber_instance = Subscriber(forex_provider_address)
    subscriber_instance.run()
