LLM_RESULTS_DIR = "classifiers/llm/results"


CLASS_DESCRIPTION = {
    'entity': {
        'property_value_update': "a property value is replaced with a semantically different value, altering the statement's meaning. This includes corrections of incorrect values and updates reflecting real-world changes.",
        'refinement': "a property value is replaced by a more specific or precise value, without changing the statement's meaning. The refinement provides a more specific classification while remaining semantically compatible with the original value.",
        'unrefinement': "a property value is replaced by a less specific or precise value, without changing the statement's meaning. The unrefinement generalizes to a broader classification while remaining semantically compatible with the original value. "
    },
    'text': {
        'property_value_update': "a property value is replaced with a semantically different value, altering the statement's meaning. This includes corrections of incorrect values and updates reflecting real-world changes.",
        'refinement': "a property value is replaced by a more specific or precise value, without changing the statement's meaning. The refinement may add more contextual information or rephrase a text to convey the same meaning more clearly, while remaining semantically compatible with the original value.",
        'textual_change': "a property value of type text is modified to correct (or introduce) language errors, such as spelling, typos, or grammar, without altering sentence structure or the statement's meaning. This also covers surface-level presentation changes, such as spacing, capitalization, hyphenation, punctuation, and other typographical elements." +
        "For standard abbreviations (e.g., 'Saint' -> 'St.') we consider them as a textual_change, but for name abbreviations (e.g., 'J.' -> 'John') we consider them a refinement because there are multiple names that can start with a specific letter.",
        # 're_formatting': "a property value's representation is modified on a surface-level, without altering its underlying meaning. For text values, re-formatting covers changes to visual presentation, such as spacing, capitalization, hyphenation, and other typographical elements.",
        'unrefinement': "a property value is replaced by a less specific or precise value, without changing the statement's meaning. The unrefinement removes contextual information, while remaining semantically compatible with the original value. "
    }
}

EXAMPLES_PER_DATATYPE = {
    'entity': {
        'property_value_update': [
            ("Agnosticism (Q288928)", "Islam (Q432)"),
            ("Dewey Jackson (Q161753)", "1st arrondissement of Paris (Q161741)"),
            ("physicist (Q169470)", "director (Q1162163)"),
            ("Ministry of Finance (North Korea) (Q16182222)", "Minister of Finance (Q113947130)"),
            ("Queen Victoria (Q235199)", "Victoria (Q9439)"),
            ("McLaren F1 (Q849607)", "McLaren (Q172030)"),
        ],
        'refinement': [
            ("business (Q4830453)", "automobile manufacturer (Q786820)"),
            ("engineer (Q81096)", "electrical engineer (Q1326886)"),
            ("motorcycle sport (Q328716)", "motorcycle road racing (Q965550)"),
            ("University of London (Q170027)", "Royal Holloway, University of London (Q1202039)")
        ],
        'unrefinement': [
            ("employment agency (Q261362)", "agency (Q352450)"),
            ("city in New Jersey (Q2974552)", "city (Q515)"),
            ("twin (Q159979)", "human (Q5)")
        ]
    },
    "text": {
        "property_value_update": [
            ("Belize", "description","a country in North America", "a country in Central America"),
            ("135 and 136 Main Street","label","Including Post Office","135 and 136 Main Street"),
            ("Julia Lennon","description","Waitress, Housewife","mother of English musician John Lennon"),
            ("Dorothy Waldegrave","description","-","(est. 9 Mar 1529 - before 19 May 1597)")
        ],
        "refinement": [
            ("Sanandaj", "description", "city", "city in Iran"),
            ("Boston","description", "city in Massachusetts, United States of America", "capital city of the state of  Massachusetts, United States"),
            ("Henry Thynne, 3rd Marquess of Bath", "description", "British naval commander and politician", "British naval commander and politician (1797-1837)"),
            ("Concrete and Gold","description", "album by Foo Fighters", "Foo Fighters album"),
            ("Life Form", "label" , "A Form of life", "Life Form"),
            ("Isabelle Augenstein","description","NLP researcher in Copenhagen","researcher, natural language processing, University of Copenhagen"),
        ],
        "unrefinement": [
            ("Lions for Lambs","description", "2007 thriller movie on the war in Afghanistan directed by Robert Redford", "2007 film directed by Robert Redford"),
            ("Cladochaeta minuta","description", "species of flies", "species of insect"),
            ("Chris Isaak discography","description","Musical recordings by Chris Isaak.","artist discography"),
            ("Geʽez script","Unicode range","U+1200-137F,U+1380-139F,U+2D80-2DDF,U+AB00-AB2F","U+1200-137F"),
            ("Otto Bauer","ELNET ID","a11222621","11222621"),
        ],
        "textual_change": [
            ("Natriuretic peptide B","label","natriuretic peptide B","Natriuretic peptides B"),
            ("Tom Reichelt", "image", "REICHELT_Tom_Tour_de_Ski_2010.jpg", "REICHELT Tom Tour de Ski 2010.jpg"),
            ("Wreay CofE Primary School","phone number","+44-1697-473275","+44-16974-73275"),
            ("China Human Rights Organisations", "description", "organization",	"Organisation"),
            ("Chyler Leigh", "description", "American acterss", "American actress"),
            ("Mark Lowry", "description", "Singer-Songwriter", "singer and songwriter"),
            ("Kofi Annan","description", "The seventh Secretary-General of the United Nations", "7th Secretary-General of the United Nations"),
            ("Bosnia and Herzegovina","description","country in southeastern Europe","Country in Southeast Europe"),
            ("Jude Milhon","description", "American hacker & author", "American hacker and author"),
            ("Libation cup","description","A container used to hold and or pour a liquid in honour of a deity.","container used to hold and or pour a liquid in honour of a deity"),
        ],
        "refinement, unrefinement": [
            ("European Union","description","union of 27 states mostly located in Europe","economic and political union of states mostly located in Europe"),
            ("Samuel B. Coe","description","American politician – Minnesota -- \"S.B.\" House 1877 (District 18)","American physician and politician"),
            ("David R. Williams","description","sociologist born in 1954 in Aruba","Aruban American sociologist and professor of public health"),
            ("Christin Meyer","description","German association football player","German footballer (born 2000)")
        ],
        "textual_change, refinement": [
            ("Santiago","description","Capital of Chile","capital city of Chile"),
            ("waffle","description","food, typically eaten at breakfast","A type of food typically eaten during breakfast."),
            ("John Brown","description","NZ rugby player","New Zealand rugby league footballer")
        ],
        "textual_change, refinement": [
            ("San Francisco","description","combined city and county in California, United States","consolidated city-county in California, United States"),
            ("Kazuki Takahashi","description","Japanese footballer","JJapanese association football player")
        ],
        "textual_change, unrefinement": [
            ("Saint Martin Church","Commons category","Saint Martin Church (Roben, Gera)","St. Martin (Roben)"),
            ("Angelina Mendes Costa","description","holocaust victim, b. 1872-01-03","Holocaust victim (born 1872)")
        ]
    }
} 

CLASSES_PER_DATATYPE = {
    'text': ['textual_change', 'refinement', 'unrefinement', 'property_value_update'],
    'entity': ['refinement', 'unrefinement', 'property_value_update'] 
}

