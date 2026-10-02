from staff.scoping import CampusScopedAdminMixin

from django.contrib import admin

from .models import Survey, SurveyAnswer, SurveyChoice, SurveyQuestion, SurveyResponse


class SurveyChoiceInline(CampusScopedAdminMixin, admin.TabularInline):
    model = SurveyChoice
    extra = 1


class SurveyQuestionInline(CampusScopedAdminMixin, admin.TabularInline):
    model = SurveyQuestion
    extra = 1
    show_change_link = True


@admin.register(Survey)
class SurveyAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "is_open", "created_by", "created_at")
    list_filter = ("is_open",)
    search_fields = ("title",)
    inlines = [SurveyQuestionInline]


@admin.register(SurveyQuestion)
class SurveyQuestionAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("text", "survey", "question_type", "order")
    list_filter = ("question_type", "survey")
    inlines = [SurveyChoiceInline]


@admin.register(SurveyResponse)
class SurveyResponseAdmin(CampusScopedAdminMixin, admin.ModelAdmin):
    list_display = ("survey", "member", "submitted_at")
    list_filter = ("survey",)


admin.site.register(SurveyAnswer)
