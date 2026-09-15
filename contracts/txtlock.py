# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }

import json
import re
import datetime
import hashlib
import genlayer as gl
from genlayer import *

# Enums / States
STATE_AWAITING_ESCROW = "AWAITING_ESCROW"
STATE_FUNDED = "FUNDED"
STATE_CANCELLED = "CANCELLED"
STATE_EXPIRED = "EXPIRED"
STATE_SETTLED = "SETTLED"

MARKER_NONE = "NONE"
MARKER_PAID_OPERATOR = "PAID_OPERATOR"
MARKER_REFUNDED = "REFUNDED"

OUTCOME_MATCH = "MATCH"
OUTCOME_MISMATCH = "MISMATCH"
OUTCOME_FETCH_FAILED = "FETCH_FAILED"

DOH = "https://dns.google/resolve?name={fqdn}&type=TXT"

@gl.evm.contract_interface
class _PayoutTarget:
    class View:
        pass
    class Write:
        pass

def _get_now_ts() -> int:
    raw = gl.message.raw["datetime"]
    dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return int(dt.timestamp())

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def _check_dns(fqdn: str, expected_txt: str) -> dict:
    url = DOH.format(fqdn=fqdn)
    
    try:
        response = gl.nondet.web.get(url)
    except Exception:
        return {"outcome": OUTCOME_FETCH_FAILED, "observed": ""}
        
    try:
        data = json.loads(response.body.decode("utf-8", errors="replace"))
    except Exception:
        return {"outcome": OUTCOME_FETCH_FAILED, "observed": ""}
        
    if not isinstance(data, dict):
        return {"outcome": OUTCOME_FETCH_FAILED, "observed": ""}
        
    status = data.get("Status")
    if status is None or status != 0:
        return {"outcome": OUTCOME_FETCH_FAILED, "observed": ""}
        
    answer = data.get("Answer")
    if answer is None:
        return {"outcome": OUTCOME_MISMATCH, "observed": ""}
        
    if not isinstance(answer, list):
        return {"outcome": OUTCOME_MISMATCH, "observed": ""}
        
    if len(answer) == 0:
        return {"outcome": OUTCOME_MISMATCH, "observed": ""}
        
    found_mismatch_val = ""
    for ans in answer:
        if not isinstance(ans, dict):
            continue
            
        t = ans.get("type")
        d = ans.get("data")
        
        if (t == 16 or (t is None and d is not None)) and isinstance(d, str):
            val = d.strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
                
            if val == expected_txt:
                return {"outcome": OUTCOME_MATCH, "observed": val}
            found_mismatch_val = val
            
    return {"outcome": OUTCOME_MISMATCH, "observed": found_mismatch_val}

def _validate_fqdn(fqdn: str):
    if len(fqdn) < 4 or len(fqdn) > 253:
        raise gl.vm.UserError("record_fqdn length must be 4-253 chars")
    if fqdn.startswith("http://") or fqdn.startswith("https://"):
        raise gl.vm.UserError("record_fqdn must not start with http:// or https://")
    if "." not in fqdn:
        raise gl.vm.UserError("record_fqdn must contain a dot")
    if any(c in fqdn for c in "/?# "):
        raise gl.vm.UserError("record_fqdn must not contain /, ?, # or space")
    
    if not re.match(r"^[a-z0-9._-]+$", fqdn):
        raise gl.vm.UserError("record_fqdn contains invalid characters")
        
    for label in fqdn.split("."):
        if len(label) > 63:
            raise gl.vm.UserError("record_fqdn labels must be 1-63 chars")

def _validate_txt(txt: str):
    if len(txt) < 8 or len(txt) > 128:
        raise gl.vm.UserError("expected_txt length must be 8-128 chars")
    if not re.match(r"^[A-Za-z0-9._\-=]+$", txt):
        raise gl.vm.UserError("expected_txt contains invalid characters or whitespace")

class TxtLock(gl.contract.Contract):
    depositor: str
    operator: str
    record_fqdn: str
    expected_txt: str
    expected_txt_hash: str
    hold_seconds: u256
    cancel_window_seconds: u256
    resolve_window_seconds: u256
    
    status: str
    marker: str
    verdict: str
    
    deposit: u256
    fund_ts: u256
    hold_until_ts: u256
    resolve_deadline_ts: u256
    
    observed_txt: str
    observed_hash: str
    txt_confirmed_at_fund: bool

    operator_credit: u256
    
    def __init__(
        self,
        depositor: str,
        record_fqdn: str,
        expected_txt: str,
        hold_seconds: int,
        cancel_window_seconds: int,
        resolve_window_seconds: int
    ):
        operator = str(gl.message.sender_address)
        if depositor == operator:
            raise gl.vm.UserError("depositor cannot be operator")
        if depositor == "0x0000000000000000000000000000000000000000":
            raise gl.vm.UserError("depositor cannot be zero address")
            
        fqdn = record_fqdn.lower().strip()
        _validate_fqdn(fqdn)
        
        txt = expected_txt.strip()
        _validate_txt(txt)
        
        if not (60 <= hold_seconds <= 2592000):
            raise gl.vm.UserError("hold_seconds must be 60-2592000")
        if not (0 <= cancel_window_seconds <= 86400):
            raise gl.vm.UserError("cancel_window_seconds must be 0-86400")
        if not (cancel_window_seconds < hold_seconds):
            raise gl.vm.UserError("cancel_window_seconds must be strictly < hold_seconds")
        if not (60 <= resolve_window_seconds <= 2592000):
            raise gl.vm.UserError("resolve_window_seconds must be 60-2592000")
            
        self.operator_credit = u256(0)
        self.depositor = depositor
        self.operator = operator
        self.record_fqdn = fqdn
        self.expected_txt = txt
        self.expected_txt_hash = _hash(txt)
        self.hold_seconds = u256(hold_seconds)
        self.cancel_window_seconds = u256(cancel_window_seconds)
        self.resolve_window_seconds = u256(resolve_window_seconds)
        self.status = STATE_AWAITING_ESCROW
        self.marker = MARKER_NONE
        self.verdict = ""
        self.deposit = u256(0)
        self.fund_ts = u256(0)
        self.hold_until_ts = u256(0)
        self.resolve_deadline_ts = u256(0)
        self.observed_txt = ""
        self.observed_hash = ""
        self.txt_confirmed_at_fund = False

    @gl.public.write.payable
    def fund_escrow(self) -> None:
        if self.status != STATE_AWAITING_ESCROW:
            raise gl.vm.UserError("status must be AWAITING_ESCROW")
        if str(gl.message.sender_address) != self.depositor:
            raise gl.vm.UserError("only depositor can fund")
        if gl.message.value <= 0:
            raise gl.vm.UserError("deposit must be > 0")
            
        def leader_fetch() -> str:
            res = _check_dns(self.record_fqdn, self.expected_txt)
            return json.dumps(res, sort_keys=True)
            
        raw_res = gl.eq_principle.strict_eq(leader_fetch)
        res = json.loads(raw_res)
        
        if res["outcome"] != OUTCOME_MATCH:
            raise gl.vm.UserError("txt record must already match")
            
        now_ts = _get_now_ts()
        self.deposit = u256(gl.message.value)
        self.fund_ts = u256(now_ts)
        self.hold_until_ts = u256(now_ts + self.hold_seconds)
        self.resolve_deadline_ts = u256(self.hold_until_ts + self.resolve_window_seconds)
        self.observed_txt = res["observed"]
        self.observed_hash = _hash(res["observed"])
        self.txt_confirmed_at_fund = True
        self.status = STATE_FUNDED

    @gl.public.write
    def cancel(self) -> None:
        if self.status == STATE_AWAITING_ESCROW:
            if str(gl.message.sender_address) != self.operator:
                raise gl.vm.UserError("only operator can cancel unfunded escrow")
            self.status = STATE_CANCELLED
            self.marker = MARKER_REFUNDED
            return
            
        if self.status != STATE_FUNDED:
            raise gl.vm.UserError("status must be FUNDED or AWAITING_ESCROW")
            
        if str(gl.message.sender_address) != self.depositor:
            raise gl.vm.UserError("only depositor can cancel funded escrow")
            
        now_ts = _get_now_ts()
        if now_ts >= (self.fund_ts + self.cancel_window_seconds):
            raise gl.vm.UserError("cancel window expired")
        if now_ts >= self.hold_until_ts:
            raise gl.vm.UserError("hold period expired")
            
        deposit = self.deposit
        self.deposit = u256(0)
        self.status = STATE_CANCELLED
        self.marker = MARKER_REFUNDED
        
        if deposit > 0:
            _PayoutTarget(Address(self.depositor)).emit_transfer(value=deposit)

    @gl.public.write
    def resolve(self) -> None:
        if self.status != STATE_FUNDED:
            raise gl.vm.UserError("status must be FUNDED")
        if self.marker != MARKER_NONE:
            raise gl.vm.UserError("marker must be NONE")
            
        now_ts = _get_now_ts()
        if now_ts < self.hold_until_ts:
            raise gl.vm.UserError("hold period not reached yet")
        if now_ts >= self.resolve_deadline_ts:
            raise gl.vm.UserError("resolve deadline has passed; operator cannot be paid; use expire() to refund depositor")
            
        def leader_fetch() -> str:
            res = _check_dns(self.record_fqdn, self.expected_txt)
            return json.dumps(res, sort_keys=True)
            
        raw_res = gl.eq_principle.strict_eq(leader_fetch)
        res = json.loads(raw_res)
        outcome = res["outcome"]
        
        self.verdict = outcome
        self.status = STATE_SETTLED
        
        deposit = self.deposit
        self.deposit = u256(0)
        
        if outcome == OUTCOME_MATCH:
            self.marker = MARKER_PAID_OPERATOR
            if deposit > 0:
                self.operator_credit += deposit
        else:
            self.marker = MARKER_REFUNDED
            if deposit > 0:
                _PayoutTarget(Address(self.depositor)).emit_transfer(value=deposit)

    @gl.public.write
    def expire(self) -> None:
        if self.status != STATE_FUNDED:
            raise gl.vm.UserError("status must be FUNDED")
        if self.marker != MARKER_NONE:
            raise gl.vm.UserError("marker must be NONE")
            
        now_ts = _get_now_ts()
        if now_ts < self.resolve_deadline_ts:
            raise gl.vm.UserError("resolve deadline has not passed yet")
            
        self.status = STATE_EXPIRED
        self.marker = MARKER_REFUNDED
        
        deposit = self.deposit
        self.deposit = u256(0)
        
        if deposit > 0:
            _PayoutTarget(Address(self.depositor)).emit_transfer(value=deposit)
            
    @gl.public.write
    def withdraw(self) -> None:
        if str(gl.message.sender_address) != self.operator:
            raise gl.vm.UserError("only operator can withdraw credit")
        credit = self.operator_credit
        if credit == 0:
            raise gl.vm.UserError("zero credit")
            
        self.operator_credit = u256(0)
        try:
            _PayoutTarget(Address(self.operator)).emit_transfer(value=credit)
        except Exception:
            self.operator_credit = credit
            raise gl.vm.UserError("withdraw failed")

    @gl.public.view
    def get_case(self) -> dict:
        return {
            "depositor": self.depositor,
            "operator": self.operator,
            "record_fqdn": self.record_fqdn,
            "expected_txt": self.expected_txt,
            "expected_txt_hash": self.expected_txt_hash,
            "hold_seconds": int(self.hold_seconds),
            "cancel_window_seconds": int(self.cancel_window_seconds),
            "resolve_window_seconds": int(self.resolve_window_seconds),
            "status": self.status,
            "marker": self.marker,
            "verdict": self.verdict,
            "deposit": int(self.deposit),
            "fund_ts": int(self.fund_ts),
            "hold_until_ts": int(self.hold_until_ts),
            "resolve_deadline_ts": int(self.resolve_deadline_ts),
            "observed_txt": self.observed_txt,
            "observed_hash": self.observed_hash,
            "txt_confirmed_at_fund": self.txt_confirmed_at_fund
        }

    @gl.public.view
    def get_settlement(self) -> dict:
        return {
            "status": self.status,
            "verdict": self.verdict,
            "marker": self.marker,
            "operator_payout": int(self.operator_credit) if self.marker == MARKER_PAID_OPERATOR else 0
        }

    @gl.public.view
    def get_credit(self, addr: str) -> int:
        if addr == self.operator:
            return int(self.operator_credit)
        return 0
