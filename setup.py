from setuptools import setup

setup(
   name="deploy",
   version="1.0",
   description="Tool for deploy services using kubernetes",
   author_email="fluder.tw@gmail.com",
   packages=["deploy"],
   scripts=[
      "scripts/d"
   ]
)