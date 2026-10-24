"""HTTP-маршруты пары. Не создают OnboardingSession и не читают платный отчёт."""

from __future__ import annotations

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import CompatibilityReport
from core.services.compatibility.input import CompatibilityError
from core.services.compatibility.policy import SCHEMA_VERSION
from core.services.compatibility.service import create_compatibility_report, transit_view


class CompatibilityReportCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        try:
            report = create_compatibility_report(request.data)
        except CompatibilityError as exc:
            return Response({"detail": exc.detail}, status=exc.status_code)
        document = report.public_document
        return Response(
            {
                "schema_version": SCHEMA_VERSION,
                "report_id": str(report.id),
                "status": document["status"],
                "sections": {
                    "bond": document["bond"]["status"],
                    "transits": document["transits"]["status"],
                    "signs": document["signs"]["status"],
                    "chart": document["chart"]["status"],
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CompatibilityReportDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, report_id):
        report = CompatibilityReport.objects.filter(id=report_id).first()
        if report is None:
            return Response({"detail": "Отчёт не найден."}, status=status.HTTP_404_NOT_FOUND)
        return Response(report.public_document)


class CompatibilityTransitView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, report_id):
        report = CompatibilityReport.objects.filter(id=report_id).first()
        if report is None:
            return Response({"detail": "Отчёт не найден."}, status=status.HTTP_404_NOT_FOUND)
        try:
            payload = transit_view(report, request.query_params.get("date"))
        except CompatibilityError as exc:
            return Response({"detail": exc.detail}, status=exc.status_code)
        return Response(payload)
