from django import forms

from .models import SurveyQuestion


class SurveyResponseForm(forms.Form):
    """
    A form whose fields depend on the specific survey being answered - one
    field per SurveyQuestion, built in __init__ rather than declared
    statically, since a static Form class can't know a survey's questions
    ahead of time. Used by members/views.py's survey_respond.
    """

    def __init__(self, survey, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.survey = survey
        self.question_field_names = {}
        for question in survey.questions.prefetch_related("choices").all():
            field_name = f"question_{question.id}"
            self.question_field_names[question.id] = field_name
            if question.question_type == SurveyQuestion.QuestionType.CHOICE:
                self.fields[field_name] = forms.ModelChoiceField(
                    queryset=question.choices.all(),
                    label=question.text,
                    widget=forms.RadioSelect,
                    required=False,
                    empty_label=None,
                )
            else:
                self.fields[field_name] = forms.CharField(
                    label=question.text,
                    widget=forms.Textarea(attrs={"rows": 3}),
                    required=False,
                )
