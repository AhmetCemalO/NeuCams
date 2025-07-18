from setuptools import setup
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()

setup(
      name='pco',
      packages=['pco'],
      version='0.1.3',
      license='MIT',

      description='This class provides methods for using pco cameras.',
      long_description=long_description,
      long_description_content_type='text/x-rst',

      author='Andreas Ziegler',
      author_email='andreas.ziegler@pco.de',
      url='https://www.pco.de/software/third-party-software/python/',

      keywords=[
          'pco',
          'camera',
          'flim',
          'scmos',
          'microscopy'
      ],

      install_requires=[
          'numpy'
      ],
      package_data={
          'pco': [
              'SC2_Cam.dll',
              'PCO_File.dll',
              'PCO_Recorder.dll',
              'sc2_clhs.dll',
              'sc2_cl_me4.dll',
              'LICENSE.txt'
          ]
      },
      classifiers=[
          'Development Status :: 4 - Beta',

          'Programming Language :: Python',
          'Programming Language :: Python :: 3',
          'Programming Language :: Python :: 3.5',
          'Programming Language :: Python :: 3.6',
          'Programming Language :: Python :: 3.7',
          'Programming Language :: Python :: 3.8',
          

          'License :: OSI Approved :: MIT License',

          'Operating System :: Microsoft :: Windows',
          'Operating System :: Microsoft :: Windows :: Windows 7',
          'Operating System :: Microsoft :: Windows :: Windows 8',
          'Operating System :: Microsoft :: Windows :: Windows 8.1',
          'Operating System :: Microsoft :: Windows :: Windows 10',

          'Topic :: Scientific/Engineering'
      ]
)
