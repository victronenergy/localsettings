DESCRIPTION = "Localsettings python scripts"
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COREBASE}/LICENSE;md5=3f40d7994397109285ec7b81fdeb3b58 \
                    file://${COREBASE}/meta/COPYING.MIT;md5=3da9cfbcb788c80a0384361b4de20420"

SRC_URI = "file://localsettings \
           file://*.py \
           file://Makefile \
          "

S = "${WORKDIR}"

inherit allarch

PR = "r1"

EXTRA_OEMAKE = ""

do_install () {
	oe_runmake install DESTDIR=${D} BINDIR=${bindir}
}

PARALLEL_MAKE = ""

BBCLASSEXTEND = "native"
