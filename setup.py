
import sys
from subprocess import check_call
from setuptools import setup

if __name__ == "__main__":    
    # generate resource file for PyQt5 only, quit at this point before setup
    if "generate" in sys.argv:  
        check_call("pyrcc5 res/Resources.qrc > dicombrowser/resources_rc.py", shell=True)
    else:
        setup()
