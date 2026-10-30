# PySyzygos math slides: make -> pysyzygos_math.pdf (checks the formula references in the code first)
MAIN = pysyzygos_math

all: $(MAIN).pdf

xref_table.tex: math_slides.tex $(wildcard ../../src/pysyzygos/*.py)
	python3 check_xref.py

# the release the slides apply to (title slide), from the one place for it
version.tex: ../../src/pysyzygos/version.py
	sed -nE 's/^__(version|codename)__ = "([^"]*)".*/\\newcommand{\\py\1}{\2}/p' $< > $@

$(MAIN).pdf: $(MAIN).tex preamble.tex math_slides.tex xref_table.tex version.tex $(wildcard figures/*)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN).tex

clean:
	latexmk -c $(MAIN).tex

.PHONY: all clean
