# Benchmark quality reference

The canonical real-world benchmark uses one **complete measured configuration** as the relative quality anchor for each comparison.

The anchor is the valid cache-free profile with the highest macro character accuracy; elapsed time breaks exact accuracy ties. Document accuracy, document WER and MAIUSCOLO/SCRIPT/CORSIVO reference values all come from that same profile.

Do not build a synthetic reference by independently taking the best value of every metric from different configurations. Such an envelope may never have existed in a real run and can make every measured profile fail the quality gate simultaneously.

The absolute per-document and handwriting metrics remain in the report so a relatively best profile is not mistaken for universally adequate OCR quality.
