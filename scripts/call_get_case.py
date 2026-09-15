import os
import json
from dotenv import load_dotenv

from gltest import get_contract_factory
from eth_account import Account

def test_call():
    load_dotenv()
    PRIVATE_KEY = os.environ.get("PRIVATE_KEY")
    account = Account.from_key(PRIVATE_KEY)
    
    with open("deploy/receipt.json") as f:
        receipt = json.load(f)
        
    contract_address = receipt["contract_address"]
    
    factory = get_contract_factory("TxtLock")
    contract = factory.build_contract(contract_address)
    
    print(f"Calling get_case on {contract_address} ...")
    case = contract.get_case().call()
    print("Result:")
    print(json.dumps(case, indent=2))
    
    assert case["status"] == "AWAITING_ESCROW"
    print("SUCCESS! State is readable.")
