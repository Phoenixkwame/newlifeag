from django.conf import settings
from django.db import models

from members.models import Member


class Survey(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_open = models.BooleanField(default=True, help_text="Members can respond while this is open.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class SurveyQuestion(models.Model):
    class QuestionType(models.TextChoices):
        TEXT = "text", "Open text"
        CHOICE = "choice", "Multiple choice"

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="questions")
    text = models.CharField(max_length=255)
    question_type = models.CharField(max_length=10, choices=QuestionType.choices, default=QuestionType.TEXT)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class SurveyChoice(models.Model):
    """One selectable option on a QuestionType.CHOICE question."""

    question = models.ForeignKey(SurveyQuestion, on_delete=models.CASCADE, related_name="choices")
    text = models.CharField(max_length=150)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.text


class SurveyResponse(models.Model):
    """One member's complete submission for a survey - one per member per survey."""

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="responses")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="survey_responses")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("survey", "member")
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.member} response to {self.survey}"


class SurveyAnswer(models.Model):
    """One question's answer within a SurveyResponse - text or a chosen SurveyChoice, never both."""

    response = models.ForeignKey(SurveyResponse, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(SurveyQuestion, on_delete=models.CASCADE, related_name="answers")
    text_answer = models.TextField(blank=True)
    choice = models.ForeignKey(
        SurveyChoice, on_delete=models.SET_NULL, null=True, blank=True, related_name="answers"
    )

    class Meta:
        unique_together = ("response", "question")

    def __str__(self):
        return f"Answer to {self.question}"
