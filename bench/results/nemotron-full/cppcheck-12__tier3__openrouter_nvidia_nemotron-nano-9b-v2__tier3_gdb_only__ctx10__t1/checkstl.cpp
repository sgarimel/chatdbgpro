 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#include "checkstl.h"

#include "check.h"
#include "checknullpointer.h"
#include "library.h"
#include "mathlib.h"
#include "settings.h"
#include "standards.h"
#include "symboldatabase.h"
#include "token.h"
#include "utils.h"
#include "astutils.h"
#include "pathanalysis.h"
#include "valueflow.h"

#include <algorithm>
#include <cstddef>
#include <iterator>
#include <list>
#include <map>
#include <set>
#include <sstream>
#include <utility>

// Register this check class (by creating a static instance of it)
namespace {
    CheckStl instance;
}

// CWE IDs used:
static const struct CWE CWE398(398U);   // Indicator of Poor Code Quality
static const struct CWE CWE597(597U);   // Use of Wrong Operator in String Comparison
static const struct CWE CWE628(628U);   // Function Call with Incorrectly Specified Arguments
static const struct CWE CWE664(664U);   // Improper Control of a Resource Through its Lifetime
static const struct CWE CWE667(667U);   // Improper Locking
static const struct CWE CWE704(704U);   // Incorrect Type Conversion or Cast
static const struct CWE CWE762(762U);   // Mismatched Memory Management Routines
static const struct CWE CWE786(786U);   // Access of Memory Location Before Start of Buffer
static const struct CWE CWE788(788U);   // Access of Memory Location After End of Buffer
static const struct CWE CWE825(825U);   // Expired Pointer Dereference
static const struct CWE CWE833(833U);   // Deadlock
static const struct CWE CWE834(834U);   // Excessive Iteration


void CheckStl::outOfBounds()
{
    for (const Scope *function : mTokenizer->getSymbolDatabase()->functionScopes) {
        for (const Token *tok = function->bodyStart; tok != function->bodyEnd; tok = tok->next()) {
            const Library::Container *container = getLibraryContainer(tok);
            if (!container)
                continue;
            const Token * parent = astParentSkipParens(tok);
            for (const ValueFlow::Value &value : tok->values()) {
                if (!value.isContainerSizeValue())
                    continue;
                if (value.isImpossible())
                    continue;
                if (value.isInconclusive() && !mSettings->inconclusive)
                    continue;
                if (!value.errorSeverity() && !mSettings->isEnabled(Settings::WARNING))
                    continue;

                if (value.intvalue == 0 && Token::Match(parent, ". %name% (") && container->getYield(parent->strAt(1)) == Library::Container::Yield::ITEM) {
                    outOfBoundsError(parent->tokAt(2), tok->expressionString(), &value, parent->strAt(1), nullptr);
                    continue;
                }
                if (Token::Match(tok, "%name% . %name% (") && container->getYield(tok->strAt(2)) == Library::Container::Yield::START_ITERATOR) {
                    const Token *fparent = tok->tokAt(3)->astParent();
                    const Token *other = nullptr;
                    if (Token::simpleMatch(fparent, "+") && fparent->astOperand1() == tok->tokAt(3))
                        other = fparent->astOperand2();
                    else if (Token::simpleMatch(fparent, "+") && fparent->astOperand2() == tok->tokAt(3))
                        other = fparent->astOperand1();
                    if (other && other->hasKnownIntValue() && other->getKnownIntValue() > value.intvalue) {
                        outOfBoundsError(fparent, tok->expressionString(), &value, other->expressionString(), &other->values().back());
                        continue;
                    } else if (other && !other->hasKnownIntValue() && value.isKnown() && value.intvalue==0) {
                        outOfBoundsError(fparent, tok->expressionString(), &value, other->expressionString(), nullptr);
                        continue;
                    }
                }
                if (!container->arrayLike_indexOp && !container->stdStringLike)
                    continue;
                if (value.intvalue == 0 && Token::Match(parent, "[") && tok == parent->astOperand1()) {
                    outOfBoundsError(parent, tok->expressionString(), &value, "", nullptr);
                    continue;
                }
                if (container->arrayLike_indexOp && Token::Match(parent, "[")) {
                    const ValueFlow::Value *indexValue = parent->astOperand2() ? parent->astOperand2()->getMaxValue(false) : nullptr;
                    if (indexValue && indexValue->intvalue >= value.intvalue) {
                        outOfBoundsError(parent, tok->expressionString(), &value, parent->astOperand2()->expressionString(), indexValue);
