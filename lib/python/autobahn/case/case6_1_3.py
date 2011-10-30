###############################################################################
##
##  Copyright 2011 Tavendo GmbH
##
##  Licensed under the Apache License, Version 2.0 (the "License");
##  you may not use this file except in compliance with the License.
##  You may obtain a copy of the License at
##
##      http://www.apache.org/licenses/LICENSE-2.0
##
##  Unless required by applicable law or agreed to in writing, software
##  distributed under the License is distributed on an "AS IS" BASIS,
##  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
##  See the License for the specific language governing permissions and
##  limitations under the License.
##
###############################################################################

from case import Case

class Case6_1_3(Case):

   DESCRIPTION = """Send fragmented text message, 3 fragments, first and last of length 0, middle non-empty."""

   EXPECTATION = """A message is echo'ed back to us (with payload = payload of middle fragment)."""

   def onOpen(self):
      payload = "middle frame payload"
      self.expected[Case.OK] = [("message", payload, False)]
      self.expectedClose = {"closedByMe":True,"closeCode":[self.p.CLOSE_STATUS_CODE_NORMAL],"requireClean":True}
      self.p.sendFrame(opcode = 1, fin = False, payload = "")
      self.p.sendFrame(opcode = 0, fin = False, payload = payload)
      self.p.sendFrame(opcode = 0, fin = True, payload = "")
      self.p.closeAfter(1)
