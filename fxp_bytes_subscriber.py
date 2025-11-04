import ipaddress
from array import array
from datetime import datetime, timedelta

MAX_QUOTES_PER_MESSAGE = 50
MICROS_PER_SECOND = 1_000_000


def deserialize_price(b: bytes) -> float:
	"""
	Convert a byte array from the price feed into a float.

	>>> deserialize_price(b'\xd5\xe9\xf6B')
	123.45669555664062

	:param b: byte array representing price (4 bytes, IEEE 754 binary32 little-endian)
	:return: float representation of the byte array
	"""
	a = array('f')  # 4-byte float, not 8-byte double
	a.frombytes(b)
	# No byteswap needed - already in little-endian format
	return a[0]


def serialize_address(address: (str, int)) -> bytes:
	"""
	Serialize an address tuple (IP, port) into bytes for subscription request.
	
	>>> serialize_address(('127.0.0.1', 65534))
	b'\\x7f\\x00\\x00\\x01\\xff\\xfe'
	
	:param address: tuple of (ip_string, port)
	:return: 6-byte sequence (4 bytes IP + 2 bytes port in big-endian)
	"""
	ip_bytes = ipaddress.ip_address(address[0]).packed
	port_bytes = address[1].to_bytes(2, byteorder='big')
	return ip_bytes + port_bytes


def deserialize_utcdatetime(b: bytes) -> datetime:
	"""
	Convert an 8-byte timestamp into a datetime object.
	Timestamp is microseconds since Unix epoch in big-endian format.
	
	>>> deserialize_utcdatetime(b'\\x00\\x007\\xa3e\\x8e\\xf2\\xc0')
	datetime.datetime(1971, 12, 10, 1, 2, 3, 64000)
	
	:param b: 8-byte sequence in big-endian
	:return: datetime object
	"""
	a = array('Q')  # 8-byte unsigned long long
	a.frombytes(b)
	a.byteswap()  # convert from big-endian to little-endian
	micros = a[0]
	epoch = datetime(1970, 1, 1)
	return epoch + timedelta(microseconds=micros)


def unmarshal_message(b: bytes):
	"""
	Parse a forex provider message containing one or more quotes.
	Each quote is 32 bytes:
	- Bytes 0-2: First currency (3 ASCII characters)
	- Bytes 3-5: Second currency (3 ASCII characters)
	- Bytes 6-9: Exchange rate (4 bytes, IEEE 754 binary32 little-endian)
	- Bytes 10-17: Timestamp (8 bytes, big-endian microseconds since epoch)
	- Bytes 18-31: Reserved/padding (14 bytes)
	
	:param b: bytes object containing the message (32 bytes per quote)
	:return: list of dicts: [{'cross': 'GBP/USD', 'price': 1.22041, 'timestamp': datetime}, ...]
	"""
	num_quotes = len(b) // 32
	quotes = []  # Use list, not dict
	
	for x in range(num_quotes):
		quote_bytes = b[x*32:(x+1)*32]
		quote = {}
		
		# Bytes 0-2: First currency
		curr1 = quote_bytes[0:3].decode("ascii")
		# Bytes 3-5: Second currency
		curr2 = quote_bytes[3:6].decode("ascii")
		quote["cross"] = f"{curr1}/{curr2}"
		
		# Bytes 6-9: Price (4 bytes, little-endian float)
		quote["price"] = deserialize_price(quote_bytes[6:10])
		
		# Bytes 10-17: Timestamp (8 bytes, big-endian)
		quote["timestamp"] = deserialize_utcdatetime(quote_bytes[10:18])
		
		quotes.append(quote)
		
	return quotes
