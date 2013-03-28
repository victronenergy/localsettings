PY:=/usr/bin/python2.7

all: localsettings.pyo

%.pyo: %.py $(DEPS)
	${PY} -O -m py_compile $<

clean:
	rm -f *.py? 

install: localsettings.pyo
	install -d ${DESTDIR}
	install -m 0755 $^ ${DESTDIR}

