
from DicomBrowser import main
import sys, multiprocessing

if __name__ == '__main__':
	multiprocessing.freeze_support()
	sys.exit(main(sys.argv))
	
