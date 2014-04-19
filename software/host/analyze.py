import sys, struct

class Element:
  id = 0

  def __init__(self, type, **content):
    self.type = type
    self.id = Element.id
    Element.id += 1
    self.claimed_by = []
    self.__dict__.update(content)
  
  def claim(self):
    return "CLAIM:%s" % ','.join("%d" % c for c in self.claimed_by) if len(self.claimed_by) else ""
  
  def __repr__(self):
    return "<%d %s %s>" % (self.id, self.type, self.claim())

class Packet(Element):
  def __init__(self, name, **content):
    Element.__init__(self, "PACKET", token = name, **content)

def parse_data(str):
  return {"data": str.replace(" ", "").decode('hex')[:-2]}

def parse_endpoint(str):
  address, endpoint = str.split(".")
  return {"address": int(address), "endpoint": int(endpoint)}

class Error(Element):
  def __init__(self, error):
    Element.__init__(self, "ERROR", error = error)

class Timestamp(Element):
  def __init__(self, ts):
    Element.__init__(self, "TIMESTAMP", timestamp = ts)

def parse(fn):
  cnt = 0
  for r in open(fn):
    r = r.strip()
    
    yield Timestamp(cnt)
    cnt += 1
    
    token = r[61:66].strip()

    if not token:
      yield Error("empty")
      continue
    
    
    if token == "SETUP":
      yield Packet("SETUP", **parse_endpoint(r[68:]))
    elif token in ["DATA0", "DATA1", "DATA"]:
      yield Packet(token, **parse_data(r[68:]))
    elif token == "ACK":
      yield Packet("ACK")
    elif token == "NAK":
      yield Packet("NAK")
    elif token == "IN":
      yield Packet("IN", **parse_endpoint(r[68:]))
    elif token == "OUT":
      yield Packet("OUT", **parse_endpoint(r[68:]))
    else:
      assert False, token

class Transaction(Element):
  def __init__(self, timestamp_first, timestamp_last, token, address, endpoint, data):
    Element.__init__(self, "TRANSACTION", timestamp_first = timestamp_first, timestamp_last = timestamp_last, token = token, address = address, endpoint = endpoint, data = data)

  def __repr__(self):
    return "<%d Transaction: time=%d..%d %s Addr %d EP%d Data %s %s>" % (self.id, self.timestamp_first, self.timestamp_last, self.token, self.address, self.endpoint, self.data.encode('hex'), self.claim())
  
class TransactionNak(Element):
  def __init__(self, timestamp_first, timestamp_last, token, address, endpoint):
    Element.__init__(self, "TRANSACTION_NAK", timestamp_first = timestamp_first, timestamp_last = timestamp_last, token = token, address = address, endpoint = endpoint)

  def __repr__(self):
    return "<%d Transaction: time=%d..%d %s Addr %d EP%d NAK %s>" % (self.id, self.timestamp_first, self.timestamp_last, self.token, self.address, self.endpoint, self.claim())
  
class Transfer(Element):
  def __init__(self, timestamp_first, timestamp_last, token, address, endpoint, data_in, data_out, data_setup):
    Element.__init__(self, "TRANSFER", timestamp_first = timestamp_first, timestamp_last = timestamp_last, token = token, address = address, endpoint = endpoint, data_in = data_in, data_out = data_out, data_setup = data_setup)

  def __repr__(self):
    return "<%d Transfer: time=%d..%d %s Addr %d EP%d%s%s%s %s>" % (self.id, self.timestamp_first, self.timestamp_last, self.token, self.address, self.endpoint, " SETUP=" + self.data_setup.encode('hex') if self.data_setup else "", " IN=" + self.data_in.encode('hex') if self.data_in else "", " OUT=" + self.data_out.encode('hex') if self.data_out else "", self.claim())

class ControlTransfer(Element):
  def __init__(self, timestamp, address, endpoint, bmRequestType, bRequest, wValue, wIndex, wLength, data):
    Element.__init__(self, "ControlTransfer", timestamp = timestamp, address = address, endpoint = endpoint, bmRequestType = bmRequestType, bRequest = bRequest, wValue = wValue, wIndex = wIndex, wLength = wLength, data = data)

  def __repr__(self):
    description = {
      (0x80, 0x00): "GET_STATUS",
      (0x00, 0x01): "CLEAR_FEATURE",
      (0x00, 0x03): "SET_FEATURE",
      (0x00, 0x05): "SET_ADDRESS",
      (0x80, 0x06): "GET_DESCRIPTOR",
      (0x00, 0x07): "SET_DESCRIPTOR",
      (0x80, 0x08): "GET_CONFIGURATION",
      (0x00, 0x09): "SET_CONFIGURATION",
    }.get((self.bmRequestType, self.bRequest), "")

    return "<%d Control: time=%d Addr %d EP%d bmRequestType=%02x bRequest=%02x %s wValue=%04x wIndex=%02x wLength=%02x data=%s>" % (self.id, self.timestamp, self.address, self.endpoint, self.bmRequestType, self.bRequest, description, self.wValue, self.wIndex, self.wLength, self.data.encode('hex'))
  
class MatchInstance():

  PRIORITY = 0

  def __init__(self):
    self.claimed = []

  def wait(self):
    return ([self], [])

  def pass_element(self):
    return ([self,], [])

class TransactionCompleteMatcher(MatchInstance):
  PRIORITY = -1

  def __init__(self, timestamp_first, token):
    MatchInstance.__init__(self)
    self.timestamp_first = timestamp_first
    self.timestamp_last = None
    self.data = None
    self.token = token
    self.claimed.append(self.token)
  
  def pass_element(self, element):
    self.claimed.append(element)
    if element.type == "TIMESTAMP":
      self.timestamp_last = element.timestamp
    elif element.type == "PACKET" and element.token in ["DATA", "DATA0", "DATA1"] and self.data is None:
      self.data = element.data
    elif element.type == "PACKET" and element.token == "NAK" and self.data is None:
      return ([], [(TransactionNak(self.timestamp_first, self.timestamp_last, self.token.token, self.token.address, self.token.endpoint), self.claimed)])
    elif element.type == "PACKET" and element.token == "ACK" and self.data is not None:
      return ([], [(Transaction(self.timestamp_first, self.timestamp_last, self.token.token, self.token.address, self.token.endpoint, self.data), self.claimed)])
    else:
      return ([], [])
    return ([self,], [])

class TransactionBeginMatcher(MatchInstance):
  def __init__(self):
    self.timestamp_first = None
  
  def pass_element(self, element):
    if element.type == "TIMESTAMP":
      self.timestamp_first = element.timestamp
      return self.wait()
    elif element.type == "PACKET" and element.token in ["SETUP", "IN", "OUT"]:
      return ([self, TransactionCompleteMatcher(self.timestamp_first, element)], [])
    else:
      return self.wait()

class TransferCompleteMatcher(MatchInstance):
  PRIORITY = -1

  def __init__(self, timestamp_first, transaction):
    MatchInstance.__init__(self)
    self.timestamp_first = timestamp_first
    self.timestamp_last = timestamp_first
    self.first_transaction = transaction
    self.token = self.first_transaction
    self.data_in = ""
    self.data_out = ""
    self.data_setup = ""
    self.split_nak = True
    if self.token.token == "SETUP":
      self.split_nak = False

  def pass_element(self, element):
    #print "CMP", self.first_transaction, element
    # we're only interested in transactions
    if element.type not in ["TRANSACTION", "TRANSACTION_NAK"]:
      return self.wait()

    # transaction is different type (NAK vs. ACK), if requested, split into a new transfer
    if self.split_nak and element.type != self.first_transaction.type:
      return self.end()

    # if token type (IN, SETUP, OUT) is different. SETUP tokens are terminated by zero-byte packet.
    if self.first_transaction.token in ["IN", "OUT"] and self.first_transaction.token != element.token:
      return self.end()

    # if transaction goes to different address, split into a new transfer
    if element.address != self.first_transaction.address or element.endpoint != self.first_transaction.endpoint:
      return self.end()

    self.claimed.append(element)
    assert -1 not in element.claimed_by
    element.claimed_by.append(-1)
    
    self.timestamp_last = element.timestamp_last
    # merge all data
    if element.type == "TRANSACTION":
      if self.first_transaction.type == "TRANSACTION_NAK":
        self.first_transaction = element
      if element.token == "IN":
        self.data_in += element.data
      elif element.token == "OUT":
        self.data_setup += element.data
      elif element.token == "SETUP":
        self.data_setup += element.data
      else:
        assert False, (element, element.token)
      # end transfer if short data packet detected
      if not len(element.data) or len(element.data) < len(self.first_transaction.data):
        if element.token != "SETUP":
          return self.end()
    
    return self.wait()
  
  def end(self):
    return ([], [(Transfer(self.timestamp_first, self.timestamp_last, self.token.token, self.token.address, self.token.endpoint, self.data_in, self.data_out, self.data_setup), self.claimed)])

def merge(a, b):
  return a[0] + b[0], a[1] + b[1]

class TransferBeginMatcher(MatchInstance):
  def __init__(self):
    self.timestamp_first = None

  def pass_element(self, element):
    if element.type == "TIMESTAMP":
      self.timestamp_first = element.timestamp
      return self.wait()
    elif (element.type == "TRANSACTION" or element.type == "TRANSACTION_NAK") and element.claimed_by == []:
      new_transaction = TransferCompleteMatcher(self.timestamp_first, element)
      res = merge(self.wait(), new_transaction.pass_element(element))
      return res
    else:
      return self.wait()

class ControlTransferMatcher(MatchInstance):
  def pass_element(self, element):
    if element.type == "TRANSFER" and element.token == "SETUP" and len(element.data_setup) == 8:
      bmRequestType, bRequest, wValue, wIndex, wLength = struct.unpack("<BBHHH", element.data_setup)
      controltransfer = ControlTransfer(element.timestamp_first, element.address, element.endpoint, bmRequestType, bRequest, wValue, wIndex, wLength, element.data_in if (bmRequestType & 0x80) else element.data_out)
      return ([self], [(controltransfer, [element])])
    else:
      return self.wait()

active_matchers = [TransactionBeginMatcher(), TransferBeginMatcher(), ControlTransferMatcher()]

active_elements = []

parser = parse(sys.argv[1])

all_elements = []

try:
  while True:
    e = active_elements.pop(0) if len(active_elements) else parser.next()
    all_elements.append(e)
    next_matchers = []
    for matcher in active_matchers:
      matchers, elements_and_claims = matcher.pass_element(e)
      next_matchers += matchers
      
      for element, claims in elements_and_claims:
        active_elements.append(element)
        for claim in claims:
          claim.claimed_by.append(element.id)
    active_matchers = next_matchers
    active_matchers.sort(key = lambda x: x.PRIORITY)
except StopIteration:
  pass

for e in all_elements:
  print e
