import pytest
import sys
from unittest.mock import MagicMock, patch
import json
import time
from dataclasses import dataclass

# Mock genlayer module before importing txtlock
mock_gl = MagicMock()

# Setup Address class
class Address(str):
    pass

mock_gl.Address = Address
mock_gl.u256 = int
mock_gl.contract.Contract = object

class MockUserError(Exception):
    pass

mock_gl.vm.UserError = MockUserError

def allow_storage(cls):
    return cls

def contract_interface(cls):
    return cls

mock_gl.allow_storage = allow_storage
mock_gl.evm.contract_interface = contract_interface

def public_write(func):
    return func
def public_write_payable(func):
    return func
def public_view(func):
    return func

mock_gl.public.write = public_write
mock_gl.public.write.payable = public_write_payable
mock_gl.public.view = public_view

sys.modules['genlayer'] = mock_gl

import contracts.txtlock as txtlock

class MockMessage:
    def __init__(self, sender, value=0, dt="2026-09-15T12:00:00Z"):
        self.sender_address = sender
        self.value = value
        self.raw = {"datetime": dt}

class MockResponse:
    def __init__(self, body_bytes):
        self.body = body_bytes

class MockWeb:
    def __init__(self):
        self.mock_responses = {}
        
    def get(self, url):
        if url in self.mock_responses:
            return MockResponse(self.mock_responses[url].encode("utf-8"))
        raise Exception("Not found")

class MockEqPrinciple:
    def strict_eq(self, func):
        return func()

@pytest.fixture
def mock_genlayer():
    txtlock.gl.message = MockMessage("0xoperator")
    txtlock.gl.nondet.web = MockWeb()
    txtlock.gl.eq_principle = MockEqPrinciple()
    txtlock.gl.vm.UserError = MockUserError
    
    # Mock payout target
    class MockPayoutTarget:
        def __init__(self, addr):
            self.addr = addr
        def emit_transfer(self, value):
            pass
    txtlock._PayoutTarget = MockPayoutTarget
    return txtlock.gl

def test_fund_reverts_on_mismatch_or_fetch_failed(mock_genlayer):
    # Setup contract
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    
    # Setup mock response for MISMATCH
    url = txtlock.DOH.format(fqdn="test.com")
    
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"wrongsecret\""}]
    })
    
    with pytest.raises(MockUserError, match="txt record must already match"):
        contract.fund_escrow()
        
    # Setup mock response for FETCH_FAILED
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 2, # NXDOMAIN
        "Answer": []
    })
    
    with pytest.raises(MockUserError, match="txt record must already match"):
        contract.fund_escrow()

def test_nested_json_bait_does_not_match(mock_genlayer):
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    url = txtlock.DOH.format(fqdn="test.com")
    
    # Provide a nested JSON that shouldn't trick our parser if it expects the answer list
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "{\"data\":\"secret123\"}"}] # Wait, expected_txt is "secret123", the data is '{"data":"secret123"}' which doesn't match EXACTLY "secret123".
    })
    
    with pytest.raises(MockUserError, match="txt record must already match"):
        contract.fund_escrow()
        
    # Test valid match works
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"secret123\""}]
    })
    contract.fund_escrow()
    assert contract.status == txtlock.STATE_FUNDED
    assert contract.deposit == 100

def test_resolve_reverts_after_deadline_gate(mock_genlayer):
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    
    # Fund it
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    url = txtlock.DOH.format(fqdn="test.com")
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"secret123\""}]
    })
    contract.fund_escrow()
    
    # Fast forward past resolve deadline
    # fund_ts = 12:00:00
    # hold_until = 13:00:00
    # resolve_deadline = 14:00:00
    
    # 1. Before hold period
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T12:30:00Z")
    with pytest.raises(MockUserError, match="hold period not reached yet"):
        contract.resolve()
        
    # 2. After resolve deadline
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T14:30:00Z")
    with pytest.raises(MockUserError, match="resolve deadline has passed"):
        contract.resolve()
        
    # 3. Inside resolve window
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T13:30:00Z")
    contract.resolve()
    assert contract.status == txtlock.STATE_SETTLED
    assert contract.marker == txtlock.MARKER_PAID_OPERATOR

def test_expire_refund(mock_genlayer):
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    url = txtlock.DOH.format(fqdn="test.com")
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"secret123\""}]
    })
    contract.fund_escrow()
    
    txtlock.gl.message = MockMessage("0xanyone", 0, dt="2026-09-15T13:30:00Z")
    with pytest.raises(MockUserError, match="resolve deadline has not passed yet"):
        contract.expire()
        
    txtlock.gl.message = MockMessage("0xanyone", 0, dt="2026-09-15T14:30:00Z")
    contract.expire()
    assert contract.status == txtlock.STATE_EXPIRED
    assert contract.marker == txtlock.MARKER_REFUNDED

def test_second_resolve_fails(mock_genlayer):
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    url = txtlock.DOH.format(fqdn="test.com")
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"secret123\""}]
    })
    contract.fund_escrow()
    
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T13:30:00Z")
    contract.resolve()
    
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T13:35:00Z")
    with pytest.raises(MockUserError, match="status must be FUNDED"):
        contract.resolve()

def test_withdraw_pulls_credit(mock_genlayer):
    txtlock.gl.message = MockMessage("0xoperator", 0)
    contract = txtlock.TxtLock(
        depositor="0xdepositor",
        record_fqdn="test.com",
        expected_txt="secret123",
        hold_seconds=3600,
        cancel_window_seconds=1800,
        resolve_window_seconds=3600
    )
    txtlock.gl.message = MockMessage("0xdepositor", 100, dt="2026-09-15T12:00:00Z")
    url = txtlock.DOH.format(fqdn="test.com")
    mock_genlayer.nondet.web.mock_responses[url] = json.dumps({
        "Status": 0,
        "Answer": [{"type": 16, "data": "\"secret123\""}]
    })
    contract.fund_escrow()
    
    txtlock.gl.message = MockMessage("0xanyone", 0, dt="2026-09-15T13:30:00Z")
    contract.resolve()
    assert contract.operator_credit == 100
    
    txtlock.gl.message = MockMessage("0xoperator", 0, dt="2026-09-15T13:35:00Z")
    contract.withdraw()
    assert contract.operator_credit == 0
