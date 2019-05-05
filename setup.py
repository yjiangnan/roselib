from distutils.core import setup, Extension
import os

integral_ext = Extension('rosely._integral', 
			sources = ['src/integral_wrap.cxx', 'src/integral.cpp'],
)

setup(
    name='rosely',
    description='Robust and sensitive tools for high-throughput data analysis',
    version='1.3.0',
    packages=['rosely',],
    package_dir={'rosely': '.'},
    package_data={'rosely':['HelveticaCY.dfont']},
    license='Creative Commons',
    long_description=open('README.md').read(),
    ext_modules = [integral_ext],
)
