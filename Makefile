# Makefile: A standard Makefile for hello.c

PY=/usr/bin/python2.7

all: localsettings.pyo host.pyo tracing.pyo

%.pyo: %.py $(DEPS)
	${PY} -O -m py_compile $<

clean:
	rm -f *.py? 

install: localsettings.pyo host.pyo tracing.pyo
	install -d ${DESTDIR}/${BINDIR}
	install -m 0755 $^ ${DESTDIR}/${BINDIR}/
	install -m 0755 localsettings ${DESTDIR}/${BINDIR}/
