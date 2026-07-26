"""
Hello World — minimal Colab Client example.

Usage:
    python main.py
"""

from colab import App

app = App()

@app.function
def hello() -> str:
    return "Hello from Colab!"


if __name__ == "__main__":
    result = hello.remote()
    print(result)
