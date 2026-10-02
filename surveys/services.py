from django.db.models import Count

from .models import SurveyQuestion


def aggregate_results(survey):
    """
    Per-question results for the staff results view: for a CHOICE question,
    a list of (choice, count) pairs (including choices with zero responses,
    so an unpopular option still shows up as 0 rather than disappearing);
    for a TEXT question, the raw list of submitted answers (blank ones
    skipped - nothing to show for those).
    """
    results = []
    for question in survey.questions.select_related("survey").prefetch_related("choices").all():
        if question.question_type == SurveyQuestion.QuestionType.CHOICE:
            counts = {row["choice"]: row["total"] for row in question.answers.values("choice").annotate(total=Count("id"))}
            choice_counts = [(choice, counts.get(choice.id, 0)) for choice in question.choices.all()]
            results.append({"question": question, "choice_counts": choice_counts, "text_answers": None})
        else:
            text_answers = list(
                question.answers.exclude(text_answer="").select_related("response__member").order_by("-response__submitted_at")
            )
            results.append({"question": question, "choice_counts": None, "text_answers": text_answers})
    return results
