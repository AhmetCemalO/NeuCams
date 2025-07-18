from vimba import *


def main():
    vimba = Vimba.get_instance()
    print('got instance')
    vimba._startup()
    print('startup')
    vimba._shutdown()
    print('shutdown')


if __name__ == '__main__':
    main()
