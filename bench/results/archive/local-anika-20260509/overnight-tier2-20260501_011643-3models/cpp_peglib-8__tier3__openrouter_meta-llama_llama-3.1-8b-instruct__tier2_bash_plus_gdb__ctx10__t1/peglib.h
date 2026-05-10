        }
        void visit(Anchor& ope) override {
            ope.ope_->accept(*this);
        }
        void visit(Ignore& ope) override {
            ope.ope_->accept(*this);
        }
        void visit(User& ope) override {
            done_ = true;
        }
        void visit(WeakHolder& ope) override {
            ope.weak_.lock()->accept(*this);
        }
        void visit(Holder& ope) override {
            ope.ope_->accept(*this);
        }
        void visit(DefinitionReference& ope) override {
            if (ope.name_ == name_) {
                s_ = ope.s_;
            } else if (refs_.count(ope.name_)) {
                ;
            } else {
                refs_.insert(ope.name_);
                ope.get_rule()->accept(*this);
            }
            done_ = true;
        }

        const char* s_;

    private:
        std::string           name_;
        std::set<std::string> refs_;
        bool                  done_;
    };

    void make_grammar() {
        // Setup PEG syntax parser
        g["Grammar"]    <= seq(g["Spacing"], oom(g["Definition"]), g["EndOfFile"]);
        g["Definition"] <= seq(opt(g["IGNORE"]), g["Identifier"], g["LEFTARROW"], g["Expression"]);

        g["Expression"] <= seq(g["Sequence"], zom(seq(g["SLASH"], g["Sequence"])));
        g["Sequence"]   <= zom(g["Prefix"]);
        g["Prefix"]     <= seq(opt(cho(g["AND"], g["NOT"])), g["Suffix"]);
        g["Suffix"]     <= seq(g["Primary"], opt(cho(g["QUESTION"], g["STAR"], g["PLUS"])));
        g["Primary"]    <= cho(seq(opt(g["IGNORE"]), g["Identifier"], npd(g["LEFTARROW"])),
                               seq(g["OPEN"], g["Expression"], g["CLOSE"]),
                               seq(g["Begin"], g["Expression"], g["End"]),
                               seq(g["BeginCap"], g["Expression"], g["EndCap"]),
                               g["Literal"], g["Class"], g["DOT"]);

        g["Identifier"] <= seq(g["IdentCont"], g["Spacing"]);
        g["IdentCont"]  <= seq(g["IdentStart"], zom(g["IdentRest"]));
        g["IdentStart"] <= cls("a-zA-Z_");
        g["IdentRest"]  <= cho(g["IdentStart"], cls("0-9"));

        g["Literal"]    <= cho(seq(cls("'"), anc(zom(seq(npd(cls("'")), g["Char"]))), cls("'"), g["Spacing"]),
                               seq(cls("\""), anc(zom(seq(npd(cls("\"")), g["Char"]))), cls("\""), g["Spacing"]));

        g["Class"]      <= seq(chr('['), anc(zom(seq(npd(chr(']')), g["Range"]))), chr(']'), g["Spacing"]);

        g["Range"]      <= cho(seq(g["Char"], chr('-'), g["Char"]), g["Char"]);
        g["Char"]       <= cho(seq(chr('\\'), cls("nrt'\"[]\\")),
                               seq(chr('\\'), cls("0-3"), cls("0-7"), cls("0-7")),
                               seq(chr('\\'), cls("0-7"), opt(cls("0-7"))),
                               seq(lit("\\x"), cls("0-9a-fA-F"), opt(cls("0-9a-fA-F"))),
                               seq(npd(chr('\\')), dot()));

        g["LEFTARROW"]  <= seq(lit("<-"), g["Spacing"]);
        ~g["SLASH"]     <= seq(chr('/'), g["Spacing"]);
        g["AND"]        <= seq(chr('&'), g["Spacing"]);
        g["NOT"]        <= seq(chr('!'), g["Spacing"]);
        g["QUESTION"]   <= seq(chr('?'), g["Spacing"]);
        g["STAR"]       <= seq(chr('*'), g["Spacing"]);
        g["PLUS"]       <= seq(chr('+'), g["Spacing"]);
        g["OPEN"]       <= seq(chr('('), g["Spacing"]);
        g["CLOSE"]      <= seq(chr(')'), g["Spacing"]);
        g["DOT"]        <= seq(chr('.'), g["Spacing"]);

        g["Spacing"]    <= zom(cho(g["Space"], g["Comment"]));
        g["Comment"]    <= seq(chr('#'), zom(seq(npd(g["EndOfLine"]), dot())), g["EndOfLine"]);
        g["Space"]      <= cho(chr(' '), chr('\t'), g["EndOfLine"]);
        g["EndOfLine"]  <= cho(lit("\r\n"), chr('\n'), chr('\r'));
        g["EndOfFile"]  <= npd(dot());

        g["Begin"]      <= seq(chr('<'), g["Spacing"]);
        g["End"]        <= seq(chr('>'), g["Spacing"]);

        g["BeginCap"]   <= seq(chr('$'), anc(opt(g["Identifier"])), chr('<'), g["Spacing"]);
        g["EndCap"]     <= seq(lit(">"), g["Spacing"]);

        g["IGNORE"]     <= chr('~');

        // Set definition names
        for (auto& x: g) {
            x.second.name = x.first;
        }
    }

    void setup_actions() {
        g["Definition"] = [&](const SemanticValues& sv, any& dt) {
