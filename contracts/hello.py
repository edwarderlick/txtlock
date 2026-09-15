# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
import genlayer as gl

class Hello(gl.contract.Contract):
    def __init__(self):
        pass

    @gl.public.view
    def get_hello(self) -> str:
        return "Hello World"
