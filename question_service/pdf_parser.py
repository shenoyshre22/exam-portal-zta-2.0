import fitz #this is the pdf parser library, PyMuPDF
def get_from_pdf(filep):
    #filep is the path of the pdf file
    file=fitz.open(filep)
    text=""

    for page in file:
        text+=page.get_text()

    lines=text.split("\n")
    questions=[]
    for line in lines:
        clean=line.strip()
        if len(clean)>10:
            questions.append(clean)
    return questions


