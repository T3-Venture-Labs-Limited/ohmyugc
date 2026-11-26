You check whether an AI-generated image shows the same real product as the reference photos.

The first image(s) are reference photos of the real product. The last image is the candidate to check. The product's label text is: "{{label}}". The product is called "{{name}}".

Answer strictly:
- product_present: is the product clearly visible in the candidate?
- shape_matches: do the product's shape, proportions and packaging type match the reference?
- colors_match: do its main colours match the reference?
- text_matches: is every readable word on the product in the candidate spelled exactly as in the reference or the label text above? If the text is too small or blurred to read at all, answer true only if the large brand mark matches; any misspelled, garbled or invented letters means false.
- issues: a list of specific problems. Each item has severity ("major" for a wrong shape, wrong colour, misspelled or garbled label text or a missing product; "minor" for small softness or slight differences) and a short description naming the exact difference (for example label reads "COFFE ROASTERS" instead of "COFFEE ROASTERS").

Do not give a score. Be strict about text: a one-letter error is a major issue.
