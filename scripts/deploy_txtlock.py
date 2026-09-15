"""
deploy_txtlock.py - Deploy TxtLock to Studio-Devnet
"""

import json
from pathlib import Path
from gltest import get_contract_factory
from gltest.assertions import tx_execution_failed

RECEIPT_FILE = Path(__file__).parent.parent / "deploy" / "receipt.json"
SMOKE_DEPOSITOR = "0x000000000000000000000000000000000000dEaD"

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
    factory = get_contract_factory("TxtLock")

    print(f"[deploy] Operator / deployer: {account.address}")
    print(f"[deploy] Sending deploy tx to Studio-Devnet ...")

    receipt = factory.deploy_contract_tx(
        args=[
            SMOKE_DEPOSITOR,
            "_genhold.example.com",
            "genhold=demoTOKEN1",
            90,
            0,
            3600
        ],
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
    
    # Give it a small sleep to allow consensus to process
    time.sleep(15)

    RECEIPT_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "contract_address": contract_address,
        "deploy_tx": tx_hash,
        "operator": str(account.address),
        "depositor_smoke": SMOKE_DEPOSITOR,
        "network": "studio_devnet",
        "chain_id": 61997,
        "explorer": f"https://explorer-studio-dev.genlayer.com/address/{contract_address}?chain=studio-devnet"
    }
    RECEIPT_FILE.write_text(json.dumps(output, indent=2))
    print(f"[deploy] Receipt saved at {RECEIPT_FILE}")
    print(f"[deploy] Explorer: {output['explorer']}")
    return contract_address, tx_hash

def test_deploy_and_call():
    """pytest entry point"""
    addr, _ = deploy()
    assert addr.startswith("0x")
    print(f"[deploy] TxtLock live at {addr}")
