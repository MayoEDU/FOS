// The eye fit's words on the panel: point names, why a fit stopped, and the numbers behind it, and how it ended for
// its record. Kept apart from the drawing so they are tested on their own (text_test.cpp).
#pragma once

#include "gaze_fit.h"
#include "i18n.h"
#include "report.h"

#include <string>
#include <vector>

/**
 * The name of an eye fit point.
 * @param t texts
 * @param point the point
 * @return the name ("正面" / "center")
 */
const char* pointName(const UiText& t, gaze_fit::Point point);

/**
 * Why an eye fit stopped, in words.
 * @param t texts
 * @param fit the session
 * @return the text ("" if it did not fail)
 */
std::string failureText(const UiText& t, const gaze_fit::View& fit);

/**
 * The numbers behind a failure, one line: where, what was measured against what was needed, and the tries.
 * @param t texts
 * @param fit the session
 * @return the line, e.g. "正面の点: 使えたサンプル 30/45・ばらつき 3.4°（2.7° まで）・3 回" ("" if there are none)
 */
std::string failureDetailText(const UiText& t, const gaze_fit::View& fit);

/**
 * After a fit, the note on each eye the eye camera stood in for (gaze_fit::Notes::standIn): Valve read it stuck at 0,
 * the camera saw it open, and a whole fit kept its lid fit. One line per eye, split by '\n' ("" for none, or if the fit
 * isn't done).
 * @param t texts
 * @param fit the session
 * @return the note
 */
std::string standInText(const UiText& t, const gaze_fit::View& fit);

/**
 * The eyelid lines of the fit's result box: one per eye, its readings (fitLidFormat) for a fitted eye and "not fitted"
 * (fitLidNoneFormat) for the other (a first whole fit with an eye the eye camera stood in for writes only the other
 * eye's lid fit), or one "not fitted" line (fitLidsNone) with neither.
 * @param t texts
 * @param values the lid readings (those of a fitted eye are set)
 * @param fitted whether each eye's lid fit is all there (FitInConfig::lidsFitted)
 * @return the lines
 */
std::vector<std::string> lidFitLines(const UiText& t, const gaze_fit::Values& values, const bool fitted[2]);

/**
 * Whether a fit was stopped rather than failed: "Stop", another tab or page, the dashboard opened. Nothing went
 * wrong, and nothing was changed.
 * @param fit the session
 * @return true if stopped
 */
bool fitStopped(const gaze_fit::View& fit);

/**
 * How an eye fit ended, for its record (Japanese and English): done with its gaze center (and standInText), stopped
 * (fitStopped; not a failure, as on the tab) with why, or failed with why and the numbers behind it.
 * @param s the record's summary
 * @param fit the session as it ended
 */
void fillFitResult(report::Summary& s, const gaze_fit::View& fit);
