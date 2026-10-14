import { libraryExportResponse, libraryImportResponse } from "../../../../src/library-routes";
import { backend } from "../../../../local/host";

/** Library spreadsheets: GET exports a table, POST imports a CSV or Excel file. */
export const GET = (request: Request) => libraryExportResponse(backend, request);
export const POST = (request: Request) => libraryImportResponse(backend, request);
