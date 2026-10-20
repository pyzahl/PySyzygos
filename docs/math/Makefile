# PySyzygos math slides: make -> pysyzygos_math.pdf (checks the formula references in the code first)
MAIN = pysyzygos_math

all: $(MAIN).pdf

xref_table.tex: math_slides.tex $(wildcard ../../src/pysyzygos/*.py)
	python3 check_xref.py

$(MAIN).pdf: $(MAIN).tex preamble.tex math_slides.tex xref_table.tex $(wildcard figures/*)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN).tex

clean:
	latexmk -c $(MAIN).tex

.PHONY: all clean
