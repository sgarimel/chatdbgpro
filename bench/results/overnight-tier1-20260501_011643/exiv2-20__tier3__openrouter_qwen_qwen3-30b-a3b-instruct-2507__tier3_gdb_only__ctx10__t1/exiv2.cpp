
int Params::evalPrintFlags(const std::string& optArg)
{
    int rc = 0;
    switch (action_) {
    case Action::none:
        action_ = Action::print;
        printMode_ = pmList;
        for (auto&& i : optArg) {
            switch (i) {
                case 'E':
                    printTags_ |= Exiv2::mdExif;
                    break;
                case 'I':
                    printTags_ |= Exiv2::mdIptc;
                    break;
                case 'X':
                    printTags_ |= Exiv2::mdXmp;
                    break;
                case 'x':
                    printItems_ |= prTag;
                    break;
                case 'g':
                    printItems_ |= prGroup;
                    break;
                case 'k':
                    printItems_ |= prKey;
                    break;
                case 'l':
                    printItems_ |= prLabel;
                    break;
                case 'n':
                    printItems_ |= prName;
                    break;
                case 'y':
                    printItems_ |= prType;
                    break;
                case 'c':
                    printItems_ |= prCount;
                    break;
                case 's':
                    printItems_ |= prSize;
                    break;
                case 'v':
                    printItems_ |= prValue;
                    break;
                case 't':
                    printItems_ |= prTrans;
                    break;
                case 'h':
                    printItems_ |= prHex;
                    break;
                case 'V':
                    printItems_ |= prSet | prValue;
                    break;
                default:
                    std::cerr << progname() << ": " << _("Unrecognized print item") << " `" << i << "'\n";
                    rc = 1;
                    break;
            }
        }
        break;
    case Action::print:
        std::cerr << progname() << ": "
                  << _("Ignoring surplus option -P") << optArg << "\n";
        break;
    default:
        std::cerr << progname() << ": "
                  << _("Option -P is not compatible with a previous option\n");
        rc = 1;
        break;
    }
    return rc;
} // Params::evalPrintFlags

int Params::evalDelete(const std::string& optArg)
{
    int rc = 0;
    switch (action_) {
    case Action::none:
        action_ = Action::erase;
        target_ = 0;
        // fallthrough
    case Action::erase:
        rc = parseCommonTargets(optArg, "erase");
        if (rc > 0) {
            target_ |= rc;
            rc = 0;
        }
        else {
            rc = 1;
        }
        break;
    default:
        std::cerr << progname() << ": "
                  << _("Option -d is not compatible with a previous option\n");
        rc = 1;
        break;
    }
    return rc;
} // Params::evalDelete
