"""
deploy_hello.py - Deploy Hello to Studio-Devnet
"""

import json
from pathlib import Path
from gltest import get_contract_factory
from gltest.assertions import tx_execution_failed

def deploy():
    import os
    import time
    from eth_account import Account
    from dotenv import load_dotenv
    load_dotenv()
    
    key = os.environ.get("PRIVATE_KEY")
    if not key:
        raise ValueError("PRIVATE_KEY environment variable is not set")
    account = Account.from_key(key)
    factory = get_contract_factory("Hello")

    print(f"[deploy] Deployer: {account.address}")
    print(f"[deploy] Sending deploy tx to Studio-Devnet ...")

    receipt = factory.deploy_contract_tx(
        args=[],
        account=account,
        fees={
            "distribution": {
                "leaderTimeunitsAllocation": 100,
                "validatorTimeunitsAllocation": 200,
                "appealRounds": 0,
                "executionBudgetPerRound": 100000000000000000,
                "executionConsumed": 0,
                "totalMessageFees": 0,
                "rotations": [3],
                "maxPriceGenPerTimeUnit": 2,
                "storageFeeMaxGasPrice": 300000000,
                "receiptFeeMaxGasPrice": 300000000
            }
        },
        fee_value=500000000000010352,
    )

    if tx_execution_failed(receipt):
        payload = (receipt.get("consensus_data") or {}).get("leader_receipt") or receipt
        raise RuntimeError(f"[deploy] Deploy tx failed:\n{json.dumps(payload, indent=2, default=str)}")

    contract_address = receipt["data"]["contract_address"]
    tx_hash = receipt["hash"]
    print(f"[deploy] Deploy tx:       {tx_hash}")
    print(f"[deploy] Contract address: {contract_address}")
    print(f"[deploy] Status: ACCEPTED")
    
    return contract_address

def test_deploy_and_call():
    """pytest entry point"""
    addr = deploy()
    assert addr.startswith("0x")
    print(f"[deploy] Hello live at {addr}")
    
    import os
    from eth_account import Account
    key = os.environ.get("PRIVATE_KEY")
    account = Account.from_key(key)
    factory = get_contract_factory("Hello")
    contract = factory.get_contract(addr)
    
    res = contract.get_hello(account=account)
    print(f"[call] get_hello() -> {res}")
    assert res == "Hello World"
