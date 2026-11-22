
const lowp vec3 c_LumaCoefficients = vec3(0.2126, 0.7152, 0.0722);


#ifdef ANDROID

//Some android drivers think function arguments don't match if the precision is different (the spec clearly says it shouldn't matter).
//Instead of having to define a million different overloads to match all the combinations turn this into macros so it works in all cases.

//~rrr ->

#define applyLightmapToColour( colour, lightmapColour ) colour.rgb *= lightmapColour.rgb;

#define applyLightmapIntensityToColour( colour, lightmapColour, cutoff ) { mediump float c = min( lightmapColour.g * (cutoff), 1.0 ); colour *= c * c; }

#define scaleAndBiasNormal(normal) vec3( (normal * 2.0) - 1.0 )

#define halfAngleSpecular( halfVector, normal, specularPower ) pow( max( 0.0, dot( normal, halfVector ) ), specularPower )

#define calcHalfAngleVector( eyeToVertex, vertexToLight ) vertexToLight * length(eyeToVertex) - eyeToVertex

#define calcDetailMapCoordMat( vertexPos, detailFrequency, viewToModel, result ) { lowp vec4 eyeView = vec4(vec3(0.0), 1.0); mediump float quanta = 8.0 / detailFrequency; highp vec3 eyeToModel = (viewToModel * eyeView).xyz; highp vec2 detailAnchor = floor(eyeToModel.xz / quanta) * quanta; highp vec2 qPos = vec2( vertexPos.x, vertexPos.z ) - detailAnchor; result = qPos * detailFrequency; }

#define calcDetailMapCoordVec( vertexPos, eyePosModelSpace, detailFrequency, result ) { mediump float quanta = 8.0 / detailFrequency; highp vec2 detailAnchor = floor(eyePosModelSpace.xz / quanta) * quanta; highp vec2 qPos = vec2( vertexPos.x, vertexPos.z ) - detailAnchor; result = qPos * detailFrequency; }

#define getColourFromLightmap( lightMap ) lightMap * 2.0

//~rrr <-

#else//ANDROID

void applyLightmapToColour( inout lowp vec3 colour, in lowp vec3 lightmapColour )
{
    colour *= lightmapColour;
}

void applyLightmapToColour( inout lowp vec4 colour, in lowp vec4 lightmapColour )
{
	colour.rgb *= lightmapColour.rgb;
}

void applyLightmapIntensityToColour( inout lowp vec3 colour, in lowp vec3 lightmapColour, in mediump float cutoff )
{
    //colour *= dot(lightmapColour, c_LumaCoefficients);
	//colour *= (lightmapColour.g * lightmapColour.g);
	mediump float c = min( lightmapColour.g * cutoff, 1.0 );
	colour *= c * c;
}

mediump vec3 scaleAndBiasNormal( in mediump vec3 normal )
{
	return vec3( (normal * 2.0) - 1.0 );
}

highp float halfAngleSpecular( in highp vec3 halfVector, in highp vec3 normal, in highp  float specularPower )
{
    return pow( max( 0.0, dot( normal, halfVector ) ), specularPower );
}

highp vec3 calcHalfAngleVector( in highp vec3 eyeToVertex, in highp vec3 vertexToLight )
{
    return vertexToLight * length(eyeToVertex) - eyeToVertex;
}
	
void calcDetailMapCoordMat( in highp vec3 vertexPos, in mediump float detailFrequency, in highp mat4 viewToModel, out mediump vec2 result )
{
	// Texture coord correction for iPad2
	lowp vec4 eyeView = vec4(vec3(0.0), 1.0);
	mediump float quanta = 8.0 / detailFrequency;
	highp vec3 eyeToModel = (viewToModel * eyeView).xyz;
	highp vec2 detailAnchor = floor(eyeToModel.xz / quanta) * quanta;
	highp vec2 qPos = vec2( vertexPos.x, vertexPos.z ) - detailAnchor;
	result = qPos * detailFrequency;
}

void calcDetailMapCoordVec(in highp vec3 vertexPos, in highp vec3 eyePosModelSpace, in mediump float detailFrequency, out mediump vec2 result )
{
	mediump float quanta = 8.0 / detailFrequency;
	highp vec2 detailAnchor = floor(eyePosModelSpace.xz / quanta) * quanta;
	highp vec2 qPos = vec2( vertexPos.x, vertexPos.z ) - detailAnchor;
	result = qPos * detailFrequency;
}

lowp vec3 getColourFromLightmap( in lowp vec3 lightMap )
{
	return lightMap * 2.0;
}

#endif//ANDROID

void calculateCheapHeadLightCoeff( in highp vec3 pos, in mediump vec4 falloff, in mediump vec2 atten, out mediump float result )
{
	mediump float PdotL = normalize(pos).z;
	mediump float attenCoeff = clamp(0.3 * atten.x / pos.z, 0.0, 0.3 * atten.y);
	mediump float falloffCoeff = clamp((PdotL - falloff.x) * falloff.y, 0.0, 1.0);
	result = attenCoeff * falloffCoeff;
}

void calculateHeadLightCoeff( in mediump vec3 normal, in highp vec3 pos, in mediump vec4 falloff, in mediump vec2 atten, out mediump float result )
{
	mediump vec3 P = normalize(pos);
	mediump vec3 N = normalize(normal);
	mediump float PdotN = max(0.0, dot(P * -1.0, N));

	P.y *= falloff.w;
	P = normalize(P);
	mediump float PdotL = max(0.0, P.z);

	mediump float attenCoeff = clamp(atten.x / pos.z, 0.0, atten.y);
	mediump float falloffCoeff = clamp((PdotL - falloff.x) * falloff.y, 0.0, 1.0);
	result =  PdotN * attenCoeff * falloffCoeff;
}

// This is the calculation of the tyre radius.
// It has been moved from the carv.xsh because it's used in multiple places. 
highp vec4 tyreInnerRadiusScale(in highp mat4 ModelToProj, in highp vec3 vertexPosition, in highp vec4 tyreGeometry, in highp vec4 tyreRatio, out highp float fTyreVertexRadiusBlend)
{
	highp float fDefaultTyreOuterRadius = tyreGeometry.z;
    highp float fTyreInside = step(tyreGeometry.w, vertexPosition.x);

	highp float fDefaultTyreInnerRadius = tyreGeometry.x * fTyreInside + tyreGeometry.y * (1.0 - fTyreInside);
	highp float fDefaultTyreRadiusRange = fDefaultTyreOuterRadius - fDefaultTyreInnerRadius;
	highp float fDefaultTyreRatio = fDefaultTyreRadiusRange / fDefaultTyreOuterRadius;
	highp float fTyreRatio = tyreRatio.x * fTyreInside + tyreRatio.y * (1.0 - fTyreInside);

	highp float fTyreVertexRadius = length(vertexPosition.yz);
	fTyreVertexRadiusBlend = (fTyreVertexRadius - fDefaultTyreInnerRadius) / fDefaultTyreRadiusRange;
	fTyreVertexRadiusBlend = clamp(fTyreVertexRadiusBlend, 0.0, 1.0);

	highp float fTyreVertexRadiusScale = mix((1.0 - fTyreRatio) / (1.0 - fDefaultTyreRatio), 1.0, fTyreVertexRadiusBlend);
	highp vec4 pos = ModelToProj * vec4( vertexPosition.x, vertexPosition.y * fTyreVertexRadiusScale, vertexPosition.z * fTyreVertexRadiusScale, 1.0);

    return pos;
}

